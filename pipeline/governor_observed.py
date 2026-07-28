"""OpenTelemetry wrapper around the proven Pipeline Governor runtime."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time
from typing import Any, Sequence

from governor_runtime import PipelineGovernor as RuntimePipelineGovernor
from governor_types import (
    artifact_signature,
    classify_command,
    classify_failure,
    failure_fingerprint,
    signatures_differ,
)
from observability import create_session


class PipelineGovernor(RuntimePipelineGovernor):
    """Runtime Governor with optional traces/metrics and unchanged control policy."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.telemetry = None
        super().__init__(*args, **kwargs)
        try:
            # Existing render artifacts already upload governor/**.  Keep the
            # telemetry there while preserving build/<slug>/telemetry as the
            # stable local path used by tools and tests.
            target = self.directory / "telemetry"
            stable = self.build_dir / "telemetry"
            target.mkdir(parents=True, exist_ok=True)
            if not stable.exists():
                try:
                    stable.symlink_to(target, target_is_directory=True)
                except OSError:
                    stable.mkdir(parents=True, exist_ok=True)
            self.telemetry = create_session(
                self.build_dir,
                run_id=self.run_id,
                github_run_id=self.github_run_id,
                mode=self.mode,
            )
            self.telemetry.add_event(
                "governor_started",
                {
                    "mode": self.mode,
                    "github_run_id": self.github_run_id or "",
                    "build_dir": str(self.build_dir),
                },
            )
        except Exception:
            self.telemetry = None

    def record_event(self, event: str, **payload: Any) -> None:
        super().record_event(event, **payload)
        telemetry = getattr(self, "telemetry", None)
        if telemetry is not None:
            try:
                telemetry.add_event(event, payload)
            except Exception:
                pass

    def run(
        self,
        command: Sequence[str] | str,
        *,
        stage_override: str | None = None,
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        shell = bool(kwargs.get("shell", False))
        spec = classify_command(
            command,
            self.build_dir,
            shell=shell,
            stage_override=stage_override,
        )
        before = artifact_signature(self.build_dir)
        started = time.monotonic()
        handle = None
        if self.telemetry is not None:
            try:
                handle = self.telemetry.start_stage(
                    stage=spec.name,
                    item=spec.item,
                    label=spec.label,
                    attributes={
                        "pipeline.policy.mode": self.mode,
                        "pipeline.retry_safe": spec.retry_safe,
                        "pipeline.expected_output_count": len(spec.expected_outputs),
                    },
                )
            except Exception:
                handle = None

        try:
            result = super().run(
                command,
                stage_override=stage_override,
                **kwargs,
            )
        except subprocess.CalledProcessError as exc:
            duration = time.monotonic() - started
            after = artifact_signature(self.build_dir)
            error_text = str(exc.stderr or exc.output or exc)
            failure_class = classify_failure(error_text)
            fingerprint = failure_fingerprint(spec.name, "failure", error_text)
            if handle is not None and self.telemetry is not None:
                try:
                    self.telemetry.finish_stage(
                        handle,
                        status="failure",
                        returncode=int(exc.returncode),
                        duration_s=duration,
                        timed_out=int(exc.returncode) == 124,
                        failure_class=failure_class,
                        fingerprint=fingerprint,
                        made_progress=signatures_differ(before, after),
                        artifact_after=after,
                    )
                except Exception:
                    pass
            raise

        duration = time.monotonic() - started
        after = artifact_signature(self.build_dir)
        returncode = int(result.returncode)
        timed_out = returncode == 124 or "GovernorTimeout:" in str(result.stderr or "")
        status = "success" if returncode == 0 else ("timeout" if timed_out else "failure")
        error_text = str(result.stderr or result.stdout or "")
        failure_class = classify_failure(error_text) if returncode else None
        fingerprint = (
            failure_fingerprint(spec.name, status, error_text) if returncode else None
        )
        if handle is not None and self.telemetry is not None:
            try:
                self.telemetry.finish_stage(
                    handle,
                    status=status,
                    returncode=returncode,
                    duration_s=duration,
                    timed_out=timed_out,
                    failure_class=failure_class,
                    fingerprint=fingerprint,
                    made_progress=signatures_differ(before, after),
                    artifact_after=after,
                )
            except Exception:
                pass
        return result

    def finalize(self, status: str, **kwargs: Any) -> dict[str, Any]:
        summary = super().finalize(status, **kwargs)
        if self.telemetry is not None:
            try:
                self.telemetry.finish_run(status, summary)
            except Exception:
                pass
        return summary
