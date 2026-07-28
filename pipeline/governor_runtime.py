"""Runtime process supervision for the video Pipeline Governor."""
from __future__ import annotations

import dataclasses
import datetime as _dt
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from typing import Any, Iterable, Sequence

from governor_summary import GovernorSummaryMixin
from governor_types import (
    MEDIA_SUFFIXES,
    POLICIES,
    SCHEMA_VERSION,
    PolicyDecision,
    StageSpec,
    _command_parts,
    artifact_signature,
    atomic_write_json,
    classify_command,
    classify_failure,
    failure_fingerprint,
    load_json,
    normalize_error,
    percentile,
    redact_secrets,
    signatures_differ,
    utc_now,
)


class PipelineGovernor(GovernorSummaryMixin):
    """Stage-aware process supervisor and run flight recorder."""

    def __init__(
        self,
        build_dir: str | os.PathLike[str],
        *,
        repo_root: str | os.PathLike[str] | None = None,
        mode: str | None = None,
        heartbeat_seconds: float | None = None,
    ) -> None:
        self.build_dir = Path(build_dir).resolve()
        self.repo_root = Path(repo_root).resolve() if repo_root else Path(__file__).resolve().parents[1]
        self.mode = mode or os.environ.get("GOVERNOR_MODE", "recover")
        self.run_id = os.environ.get("GOVERNOR_RUN_ID") or uuid.uuid4().hex
        os.environ.setdefault("GOVERNOR_RUN_ID", self.run_id)
        self.github_run_id = os.environ.get("GITHUB_RUN_ID")
        self.heartbeat_seconds = float(
            heartbeat_seconds if heartbeat_seconds is not None
            else os.environ.get("GOVERNOR_HEARTBEAT_SECONDS", "15")
        )
        self.artifact_poll_seconds = max(0.25, float(
            os.environ.get("GOVERNOR_ARTIFACT_POLL_SECONDS", "2")
        ))
        default_console = "1" if os.environ.get("GITHUB_ACTIONS") else "0"
        self.console_heartbeats = os.environ.get("GOVERNOR_CONSOLE_HEARTBEATS", default_console) == "1"
        self.directory = self.build_dir / "governor"
        self.events_path = self.directory / "events.jsonl"
        self.current_path = self.directory / "current.json"
        self.summary_path = self.build_dir / "governor-summary.json"
        self.directory.mkdir(parents=True, exist_ok=True)
        self._history = self._load_history()
        self._policy_cache: dict[str, PolicyDecision] = {}
        self.record_event(
            "governor_started",
            mode=self.mode,
            github_run_id=self.github_run_id,
            build_dir=str(self.build_dir),
        )

    def _load_history(self) -> dict[str, list[float]]:
        history: dict[str, list[float]] = {}
        build_root = self.repo_root / "build"
        try:
            summaries = sorted(
                build_root.glob("*/governor-summary.json"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )[:250]
        except OSError:
            summaries = []
        for path in summaries:
            # At initialization this path, when present, represents a prior run
            # of the same slug and is valid historical evidence.
            summary = load_json(path, {}) or {}
            for stage, metrics in (summary.get("stages") or {}).items():
                samples = metrics.get("success_durations_s") or metrics.get("duration_samples_s") or []
                bucket = history.setdefault(stage, [])
                for value in samples:
                    try:
                        if 0 < float(value) < 86_400:
                            bucket.append(float(value))
                    except (TypeError, ValueError):
                        continue
                if len(bucket) > 200:
                    del bucket[:-200]
        return history

    def policy_for(self, stage: str, explicit_timeout: float | None = None) -> PolicyDecision:
        if explicit_timeout is not None:
            seconds = max(0.1, float(explicit_timeout))
            return PolicyDecision(seconds, seconds, seconds, "explicit", 0)
        if stage in self._policy_cache:
            return self._policy_cache[stage]
        base = POLICIES.get(stage, POLICIES["general"])
        samples = self._history.get(stage, [])
        source = "default"
        soft = float(base["soft"])
        p95: float | None = None
        if self.mode in {"tune", "recover"} and len(samples) >= 5:
            p95 = percentile(samples, 0.95)
            learned = p95 * 3.0 + 30.0
            soft = min(float(base["hard"]) * 0.85, max(float(base["floor"]), learned))
            source = "history"
        idle = min(float(base["idle"]), soft)
        # Do not call a process idle before at least half its learned soft limit.
        idle = max(idle, soft * 0.5)
        decision = PolicyDecision(
            round(soft, 2),
            round(idle, 2),
            float(base["hard"]),
            source,
            len(samples),
            round(p95, 2) if p95 is not None else None,
        )
        self._policy_cache[stage] = decision
        return decision

    def record_event(self, event: str, **payload: Any) -> None:
        record = {
            "schema_version": SCHEMA_VERSION,
            "event_id": uuid.uuid4().hex,
            "timestamp": utc_now(),
            "run_id": self.run_id,
            "slug": self.build_dir.name,
            "event": event,
            **payload,
        }
        self.directory.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        fd = os.open(self.events_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)

    def write_current(self, **payload: Any) -> None:
        atomic_write_json(
            self.current_path,
            {
                "schema_version": SCHEMA_VERSION,
                "timestamp": utc_now(),
                "run_id": self.run_id,
                "slug": self.build_dir.name,
                **payload,
            },
        )

    def run(
        self,
        command: Sequence[str] | str,
        *,
        stage_override: str | None = None,
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        """Run a child process with heartbeats, adaptive bounds, and cleanup.

        The return shape matches ``subprocess.run(..., capture_output=True,
        text=True)`` so it can replace the pipeline's existing ``sh`` helper.
        """
        shell = bool(kwargs.pop("shell", False))
        explicit_timeout = kwargs.pop("timeout", None)
        check = bool(kwargs.pop("check", False))
        cwd = kwargs.pop("cwd", None)
        env = kwargs.pop("env", None)
        input_value = kwargs.pop("input", None)
        capture_output = bool(kwargs.pop("capture_output", True))
        text_mode = bool(kwargs.pop("text", True))
        encoding = kwargs.pop("encoding", "utf-8") or "utf-8"
        errors = kwargs.pop("errors", "replace") or "replace"
        if kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise TypeError(f"unsupported subprocess options for Governor: {unexpected}")

        spec = classify_command(command, self.build_dir, shell=shell, stage_override=stage_override)
        policy = self.policy_for(spec.name, explicit_timeout)
        command_parts = _command_parts(command, shell=shell)
        safe_command = [normalize_error(part, limit=160) for part in command_parts]
        started_wall = utc_now()
        started = time.monotonic()
        artifact_before = artifact_signature(self.build_dir)
        self.record_event(
            "stage_start",
            stage=spec.name,
            item=spec.item,
            label=spec.label,
            command=safe_command,
            policy=dataclasses.asdict(policy),
            artifact_before=artifact_before,
        )
        self.write_current(
            state="running",
            stage=spec.name,
            item=spec.item,
            started_at=started_wall,
            policy=dataclasses.asdict(policy),
        )
        if self.console_heartbeats:
            print(
                f"GOVERNOR stage={spec.label} state=start "
                f"soft={policy.soft_timeout_s:.0f}s hard={policy.hard_timeout_s:.0f}s",
                flush=True,
            )

        stdout_file = tempfile.TemporaryFile()
        stderr_file = tempfile.TemporaryFile()
        process: subprocess.Popen[bytes] | None = None
        timed_out = False
        timeout_kind: str | None = None
        last_progress = started
        soft_deadline = started + policy.soft_timeout_s
        hard_deadline = started + policy.hard_timeout_s
        next_heartbeat = started + max(0.1, self.heartbeat_seconds)
        previous_sizes = (0, 0)
        previous_artifact = artifact_before
        next_artifact_poll = started

        try:
            process = subprocess.Popen(
                command,
                shell=shell,
                cwd=cwd,
                env=env,
                stdin=subprocess.PIPE if input_value is not None else subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                start_new_session=(os.name == "posix"),
            )
            if input_value is not None and process.stdin is not None:
                raw = input_value.encode(encoding) if isinstance(input_value, str) else input_value
                process.stdin.write(raw)
                process.stdin.close()

            while process.poll() is None:
                now = time.monotonic()
                try:
                    sizes = (
                        os.fstat(stdout_file.fileno()).st_size,
                        os.fstat(stderr_file.fileno()).st_size,
                    )
                except OSError:
                    sizes = previous_sizes
                current_artifact = previous_artifact
                if now >= next_artifact_poll:
                    current_artifact = artifact_signature(self.build_dir)
                    next_artifact_poll = now + self.artifact_poll_seconds
                if sizes != previous_sizes or signatures_differ(previous_artifact, current_artifact):
                    last_progress = now
                    previous_sizes = sizes
                    previous_artifact = current_artifact

                if now >= next_heartbeat:
                    self.record_event(
                        "heartbeat",
                        stage=spec.name,
                        item=spec.item,
                        pid=process.pid,
                        elapsed_s=round(now - started, 2),
                        idle_s=round(now - last_progress, 2),
                        stdout_bytes=sizes[0],
                        stderr_bytes=sizes[1],
                        artifact=current_artifact,
                    )
                    self.write_current(
                        state="running",
                        stage=spec.name,
                        item=spec.item,
                        pid=process.pid,
                        elapsed_s=round(now - started, 2),
                        idle_s=round(now - last_progress, 2),
                        artifact=current_artifact,
                    )
                    if self.console_heartbeats:
                        print(
                            f"GOVERNOR stage={spec.label} state=running "
                            f"elapsed={now - started:.0f}s idle={now - last_progress:.0f}s",
                            flush=True,
                        )
                    next_heartbeat = now + max(0.1, self.heartbeat_seconds)

                if now >= hard_deadline:
                    idle_for = now - last_progress
                    absolute_cap = started + policy.hard_timeout_s * 3.0
                    if (
                        policy.source != "explicit"
                        and idle_for < policy.idle_timeout_s
                        and now < absolute_cap
                    ):
                        extension = min(300.0, max(60.0, policy.hard_timeout_s * 0.5))
                        hard_deadline = min(absolute_cap, now + extension)
                        self.record_event(
                            "hard_timeout_extended_progress",
                            stage=spec.name,
                            item=spec.item,
                            idle_s=round(idle_for, 2),
                            new_deadline_elapsed_s=round(hard_deadline - started, 2),
                        )
                    else:
                        timed_out = True
                        timeout_kind = "hard_timeout"
                        break
                if now >= soft_deadline:
                    idle_for = now - last_progress
                    if idle_for >= policy.idle_timeout_s:
                        timed_out = True
                        timeout_kind = "stalled"
                        break
                    extension = min(180.0, max(30.0, policy.soft_timeout_s * 0.35))
                    new_deadline = min(hard_deadline, now + extension)
                    self.record_event(
                        "timeout_extended",
                        stage=spec.name,
                        item=spec.item,
                        idle_s=round(idle_for, 2),
                        old_deadline_elapsed_s=round(soft_deadline - started, 2),
                        new_deadline_elapsed_s=round(new_deadline - started, 2),
                    )
                    soft_deadline = new_deadline

                time.sleep(min(1.0, max(0.05, self.heartbeat_seconds / 5.0)))

            if timed_out and process.poll() is None:
                self._terminate_process(process)
            return_code = process.wait() if process.poll() is None else int(process.returncode or 0)
            if timed_out:
                return_code = 124
        except OSError as exc:
            return_code = 127
            stderr_file.write(str(exc).encode(encoding, errors=errors))
        finally:
            duration = time.monotonic() - started

        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout_bytes = stdout_file.read()
        stderr_bytes = stderr_file.read()
        stdout_file.close()
        stderr_file.close()
        stdout_text = stdout_bytes.decode(encoding, errors=errors)
        stderr_text = stderr_bytes.decode(encoding, errors=errors)
        if timed_out:
            detail = (
                f"\nGovernorTimeout: {spec.label} {timeout_kind} after {duration:.1f}s; "
                f"last useful progress {time.monotonic() - last_progress:.1f}s ago.\n"
            )
            stderr_text += detail

        artifact_after = artifact_signature(self.build_dir)
        status = "success" if return_code == 0 else ("timeout" if timed_out else "failure")
        remediation = []
        if return_code != 0:
            remediation = self._quarantine_invalid_outputs(spec)
        error_tail = (stderr_text or stdout_text)[-1000:]
        fingerprint = None
        failure_class = None
        if return_code != 0:
            failure_class = classify_failure(error_tail)
            fingerprint = failure_fingerprint(spec.name, status, error_tail)
        self.record_event(
            "stage_end",
            stage=spec.name,
            item=spec.item,
            label=spec.label,
            status=status,
            returncode=return_code,
            duration_s=round(duration, 3),
            stdout_tail=redact_secrets(stdout_text[-800:]),
            stderr_tail=redact_secrets(stderr_text[-800:]),
            artifact_after=artifact_after,
            made_progress=signatures_differ(artifact_before, artifact_after),
            timeout_kind=timeout_kind,
            failure_class=failure_class,
            fingerprint=fingerprint,
            remediation=remediation,
            policy=dataclasses.asdict(policy),
        )
        self.write_current(
            state=status,
            stage=spec.name,
            item=spec.item,
            returncode=return_code,
            duration_s=round(duration, 3),
            fingerprint=fingerprint,
            remediation=remediation,
        )
        if self.console_heartbeats:
            suffix = f" fingerprint={fingerprint}" if fingerprint else ""
            print(
                f"GOVERNOR stage={spec.label} state={status} "
                f"duration={duration:.1f}s rc={return_code}{suffix}",
                flush=True,
            )

        if not capture_output:
            if stdout_text:
                sys.stdout.write(stdout_text)
            if stderr_text:
                sys.stderr.write(stderr_text)
        result = subprocess.CompletedProcess(command, return_code, stdout_text if text_mode else stdout_bytes, stderr_text if text_mode else stderr_bytes)
        if check and return_code != 0:
            raise subprocess.CalledProcessError(return_code, command, output=result.stdout, stderr=result.stderr)
        return result  # type: ignore[return-value]

    def _terminate_process(self, process: subprocess.Popen[bytes]) -> None:
        self.record_event("process_termination", pid=process.pid, signal="TERM")
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
        except (OSError, ProcessLookupError):
            pass
        try:
            process.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            pass
        self.record_event("process_termination", pid=process.pid, signal="KILL")
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except (OSError, ProcessLookupError):
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    def _quarantine_invalid_outputs(self, spec: StageSpec) -> list[dict[str, str]]:
        actions: list[dict[str, str]] = []
        for path in spec.expected_outputs:
            try:
                exists = path.exists()
            except OSError:
                exists = False
            if not exists or self._output_valid(path, spec.min_output_bytes):
                continue
            suffix = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            target = path.with_name(f"{path.name}.partial.{suffix}")
            try:
                os.replace(path, target)
                action = {"action": "quarantine", "from": str(path), "to": str(target)}
            except OSError as exc:
                action = {"action": "quarantine_failed", "from": str(path), "error": str(exc)}
            actions.append(action)
            self.record_event("remediation", stage=spec.name, item=spec.item, **action)
        return actions

    @staticmethod
    def _output_valid(path: Path, minimum_bytes: int) -> bool:
        try:
            if path.stat().st_size < minimum_bytes:
                return False
        except OSError:
            return False
        suffix = path.suffix.lower()
        if suffix == ".json":
            return load_json(path, None) is not None
        if suffix in MEDIA_SUFFIXES:
            try:
                result = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                return result.returncode == 0 and float(result.stdout.strip() or "0") > 0
            except (OSError, ValueError, subprocess.TimeoutExpired):
                return False
        return True

    def events(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        try:
            with self.events_path.open(encoding="utf-8") as handle:
                for line in handle:
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if record.get("run_id") == self.run_id:
                        records.append(record)
        except OSError:
            pass
        return records

    def latest_failure(self, *, exclude_stages: Iterable[str] = ()) -> dict[str, Any] | None:
        excluded = set(exclude_stages)
        for event in reversed(self.events()):
            if (
                event.get("event") == "stage_end"
                and event.get("status") != "success"
                and event.get("stage") not in excluded
            ):
                return event
        return None
