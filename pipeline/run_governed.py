"""Run the resumable builder under a closed-loop operational Governor.

This replaces the shell loop previously used in CI.  It detects repeated
no-progress passes, retries only bounded transient failures, quarantines partial
artifacts, enforces an independent quality gate, and writes a compact summary
that future runs use to learn safer stage timeouts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Mapping

from governor import (
    PipelineGovernor,
    artifact_signature,
    atomic_write_json,
    classify_failure,
    failure_fingerprint,
    normalize_error,
    retry_budget,
    signatures_differ,
    utc_now,
)


REPAIRABLE_QUALITY_CODES = {
    "undersized_output",
    "probe_failed",
    "decode_failed",
    "invalid_duration",
    "duration_mismatch",
    "av_duration_mismatch",
    "missing_audio_stream",
}


def _marker(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    for token in ("DONE", "ERROR:", "RUN AGAIN"):
        matching = [line for line in lines if token in line]
        if matching:
            return matching[-1][-500:]
    return lines[-1][-500:] if lines else "(no process output)"


def _write_status(build_dir: Path, governor: PipelineGovernor, state: str, **payload: Any) -> None:
    atomic_write_json(
        build_dir / "render-status.json",
        {
            "schema_version": 1,
            "timestamp": utc_now(),
            "run_id": governor.run_id,
            "github_run_id": governor.github_run_id,
            "slug": build_dir.name,
            "state": state,
            **payload,
        },
    )


def _annotation(kind: str, title: str, message: str) -> None:
    safe = message.replace("\r", " ").replace("\n", " ")[:800]
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::{kind} title={title}::{safe}", flush=True)
    else:
        print(f"{kind.upper()} [{title}] {safe}", flush=True)


def _quarantine_quality_outputs(
    build_dir: Path,
    report: Mapping[str, Any],
    governor: PipelineGovernor,
) -> list[dict[str, str]]:
    failed_targets = {
        failure.get("target")
        for failure in report.get("failures", [])
        if failure.get("code") in REPAIRABLE_QUALITY_CODES
    }
    actions: list[dict[str, str]] = []
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for target in failed_targets:
        output = (report.get("outputs") or {}).get(target) or {}
        raw_path = output.get("path")
        if not raw_path:
            continue
        path = Path(str(raw_path))
        if not path.exists():
            continue
        rejected = path.with_name(f"{path.name}.quality-rejected.{stamp}")
        try:
            os.replace(path, rejected)
            action = {"action": "quality_quarantine", "from": str(path), "to": str(rejected)}
        except OSError as exc:
            action = {"action": "quality_quarantine_failed", "from": str(path), "error": str(exc)}
        actions.append(action)
        governor.record_event("remediation", stage="quality", **action)
    return actions


def _finalize_failure(
    governor: PipelineGovernor,
    build_dir: Path,
    *,
    status: str,
    passes: int,
    message: str,
    exit_code: int,
    quality_report: Mapping[str, Any] | None = None,
) -> int:
    _write_status(build_dir, governor, status, pass_number=passes, last_message=message)
    governor.finalize(status, passes=passes, quality_report=quality_report, last_message=message)
    _annotation("error", f"Governor {status}", message)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build_dir")
    parser.add_argument("--max-passes", type=int, default=200)
    parser.add_argument("--overall-timeout", type=float, default=4680.0, help="seconds")
    parser.add_argument("--max-no-progress", type=int, default=3)
    parser.add_argument("--shallow-quality", action="store_true")
    parser.add_argument("--backoff-base", type=float, default=3.0)
    args = parser.parse_args(argv)

    build_dir = Path(args.build_dir).resolve()
    if not (build_dir / "script.json").exists():
        print(f"ERROR: no script.json at {build_dir / 'script.json'}", file=sys.stderr)
        return 1

    governor = PipelineGovernor(build_dir)
    started = time.monotonic()
    deadline = started + max(30.0, args.overall_timeout)
    governed_build = Path(__file__).with_name("governed_build.py")
    quality_gate = Path(__file__).with_name("quality_gate.py")
    failure_counts: dict[str, int] = {}
    previous_message: str | None = None
    no_progress_count = 0
    quality_retry_count = 0
    last_message = "starting"

    _write_status(build_dir, governor, "starting", pass_number=0)
    print(
        f"GOVERNOR start slug={build_dir.name} run={governor.run_id} "
        f"mode={governor.mode} overall_timeout={args.overall_timeout:.0f}s",
        flush=True,
    )

    for pass_number in range(1, args.max_passes + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 30:
            return _finalize_failure(
                governor, build_dir,
                status="overall_timeout",
                passes=pass_number - 1,
                message=f"Overall render budget exhausted after {time.monotonic() - started:.1f}s",
                exit_code=124,
            )

        before = artifact_signature(build_dir)
        event_count_before = len(governor.events())
        _write_status(
            build_dir, governor, "running", pass_number=pass_number,
            elapsed_s=round(time.monotonic() - started, 2), artifact=before,
        )
        print(f"GOVERNOR pass {pass_number}/{args.max_passes} remaining={remaining:.0f}s", flush=True)
        pass_timeout = min(1800.0, max(30.0, remaining - 20.0))
        result = governor.run(
            [sys.executable, str(governed_build), str(build_dir)],
            timeout=pass_timeout,
        )
        output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
        if output:
            print(output, flush=True)
        last_message = _marker(output)
        after = artifact_signature(build_dir)
        made_progress = signatures_differ(before, after)
        governor.record_event(
            "pass_decision",
            pass_number=pass_number,
            returncode=result.returncode,
            marker=last_message,
            made_progress=made_progress,
            artifact_before=before,
            artifact_after=after,
        )

        if result.returncode == 0 and "DONE" in output:
            _write_status(build_dir, governor, "quality_check", pass_number=pass_number, last_message=last_message)
            remaining = deadline - time.monotonic()
            if remaining <= 30:
                return _finalize_failure(
                    governor, build_dir,
                    status="overall_timeout",
                    passes=pass_number,
                    message="Build completed but no time remained for the required quality gate",
                    exit_code=124,
                )
            quality_command = [sys.executable, str(quality_gate), str(build_dir)]
            if args.shallow_quality:
                quality_command.append("--shallow")
            quality_result = governor.run(
                quality_command,
                timeout=min(1500.0, max(30.0, remaining - 10.0)),
            )
            quality_output = ((quality_result.stdout or "") + "\n" + (quality_result.stderr or "")).strip()
            if quality_output:
                print(quality_output, flush=True)
            try:
                report = json.loads((build_dir / "quality_report.json").read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                report = {
                    "passed": False,
                    "failures": [{"code": "missing_quality_report", "target": "quality", "message": str(exc)}],
                    "warnings": [],
                }
            if quality_result.returncode == 0 and report.get("passed"):
                _write_status(
                    build_dir, governor, "done", pass_number=pass_number,
                    elapsed_s=round(time.monotonic() - started, 2),
                    last_message=last_message,
                    quality_warnings=len(report.get("warnings") or []),
                )
                summary = governor.finalize(
                    "done", passes=pass_number, quality_report=report, last_message=last_message,
                )
                print(
                    f"GOVERNOR DONE passes={pass_number} elapsed={time.monotonic() - started:.1f}s "
                    f"incidents={len(summary['incidents'])} warnings={len(report.get('warnings') or [])}",
                    flush=True,
                )
                for warning in report.get("warnings") or []:
                    _annotation("warning", f"Quality {warning.get('code')}", str(warning.get("message")))
                return 0

            quality_retry_count += 1
            actions = _quarantine_quality_outputs(build_dir, report, governor)
            repairable = bool(actions) and all(
                failure.get("code") in REPAIRABLE_QUALITY_CODES
                for failure in report.get("failures", [])
            )
            governor.record_event(
                "quality_decision",
                passed=False,
                retry_number=quality_retry_count,
                repairable=repairable,
                actions=actions,
                failures=report.get("failures") or [],
            )
            if repairable and quality_retry_count <= 1 and deadline - time.monotonic() > 60:
                _annotation(
                    "warning", "Quality recovery",
                    "A technically invalid final was quarantined; re-entering the resumable assembly once.",
                )
                previous_message = None
                no_progress_count = 0
                continue
            message = "; ".join(
                f"{failure.get('code')}: {failure.get('message')}"
                for failure in report.get("failures", [])
            ) or "Independent quality gate failed"
            return _finalize_failure(
                governor, build_dir,
                status="quality_failed",
                passes=pass_number,
                message=message,
                exit_code=2,
                quality_report=report,
            )

        if result.returncode == 0:
            if not made_progress and last_message == previous_message:
                no_progress_count += 1
            elif made_progress:
                no_progress_count = 0
            else:
                no_progress_count = 1
            previous_message = last_message
            if no_progress_count >= args.max_no_progress:
                fingerprint = failure_fingerprint("build", "no_progress", last_message)
                governor.record_event(
                    "circuit_breaker",
                    stage="build",
                    reason="repeated_no_progress",
                    fingerprint=fingerprint,
                    occurrences=no_progress_count,
                    marker=last_message,
                )
                return _finalize_failure(
                    governor, build_dir,
                    status="stalled",
                    passes=pass_number,
                    message=f"The same no-progress pass repeated {no_progress_count} times: {last_message}",
                    exit_code=125,
                )
            continue

        new_events = governor.events()[event_count_before:]
        root_failure = next((
            event for event in reversed(new_events)
            if event.get("event") == "stage_end"
            and event.get("status") != "success"
            and event.get("stage") not in {"build_pass", "probe"}
        ), None)
        error_text = str(
            (root_failure or {}).get("stderr_tail")
            or (root_failure or {}).get("stdout_tail")
            or output
            or last_message
        )
        failure_class = str((root_failure or {}).get("failure_class") or classify_failure(error_text))
        stage = str((root_failure or {}).get("stage") or "build")
        fingerprint = str(
            (root_failure or {}).get("fingerprint")
            or failure_fingerprint(stage, "failure", error_text)
        )
        occurrence = failure_counts.get(fingerprint, 0) + 1
        failure_counts[fingerprint] = occurrence
        budget = retry_budget(failure_class, occurrence)
        governor.record_event(
            "retry_decision",
            stage=stage,
            fingerprint=fingerprint,
            occurrence=occurrence,
            failure_class=failure_class,
            retry_budget=budget,
            normalized_error=normalize_error(error_text),
        )
        if occurrence <= budget and deadline - time.monotonic() > 60:
            delay = min(20.0, max(0.0, args.backoff_base) * (2 ** (occurrence - 1)))
            _annotation(
                "warning", f"Governor retry {occurrence}/{budget}",
                f"{stage} classified {failure_class}; retrying from checkpoints after {delay:.1f}s. "
                f"fingerprint={fingerprint}",
            )
            _write_status(
                build_dir, governor, "retrying", pass_number=pass_number,
                stage=stage, fingerprint=fingerprint, occurrence=occurrence,
                retry_in_s=delay, last_message=last_message,
            )
            if delay:
                time.sleep(delay)
            previous_message = None
            no_progress_count = 0
            continue

        governor.record_event(
            "circuit_breaker",
            stage=stage,
            reason="retry_budget_exhausted",
            fingerprint=fingerprint,
            occurrences=occurrence,
            failure_class=failure_class,
        )
        return _finalize_failure(
            governor, build_dir,
            status="failed",
            passes=pass_number,
            message=(
                f"{stage} failed ({failure_class}); retry budget {budget} exhausted. "
                f"fingerprint={fingerprint}. {last_message}"
            ),
            exit_code=result.returncode or 1,
        )

    return _finalize_failure(
        governor, build_dir,
        status="pass_limit",
        passes=args.max_passes,
        message=f"Reached the safety limit of {args.max_passes} resumable passes",
        exit_code=126,
    )


if __name__ == "__main__":
    raise SystemExit(main())
