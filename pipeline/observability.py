"""Vendor-neutral traces and metrics for the video rendering pipeline.

The Governor remains the operational source of truth.  This module mirrors its
stage lifecycle into OpenTelemetry and a durable local JSONL trace so telemetry
never becomes a production dependency.  OTLP/HTTP export is enabled only when
an OTLP endpoint is configured.
"""
from __future__ import annotations

import atexit
import dataclasses
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Mapping

SCHEMA_VERSION = 1
SERVICE_NAME = "prototype-video-renderer"
IMPORTANT_EVENTS = {
    "governor_started",
    "governor_finished",
    "retry_decision",
    "quality_decision",
    "circuit_breaker",
    "remediation",
    "process_termination",
    "timeout_extended",
    "hard_timeout_extended_progress",
    "build_pass_crash",
}

try:  # Optional by design: local renders still work before dependencies install.
    from opentelemetry import metrics as otel_metrics
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        SimpleSpanProcessor,
        SpanExporter,
        SpanExportResult,
    )
    from opentelemetry.trace import (
        NonRecordingSpan,
        SpanContext,
        Status,
        StatusCode,
        TraceFlags,
        set_span_in_context,
    )

    OTEL_AVAILABLE = True
except Exception:  # pragma: no cover - exercised by dependency-free local use.
    OTEL_AVAILABLE = False
    otel_metrics = None
    otel_trace = None
    MeterProvider = object  # type: ignore[assignment]
    PeriodicExportingMetricReader = object  # type: ignore[assignment]
    Resource = object  # type: ignore[assignment]
    TracerProvider = object  # type: ignore[assignment]
    BatchSpanProcessor = object  # type: ignore[assignment]
    SimpleSpanProcessor = object  # type: ignore[assignment]
    SpanExporter = object  # type: ignore[assignment]
    SpanExportResult = object  # type: ignore[assignment]
    NonRecordingSpan = object  # type: ignore[assignment]
    SpanContext = object  # type: ignore[assignment]
    Status = object  # type: ignore[assignment]
    StatusCode = object  # type: ignore[assignment]
    TraceFlags = object  # type: ignore[assignment]
    set_span_in_context = None


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _append_jsonl(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(_json_safe(record), ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, raw)
    finally:
        os.close(fd)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(_json_safe(payload), indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _trace_id(slug: str, run_id: str, github_run_id: str | None) -> str:
    configured = str(os.environ.get("VIDEO_TRACE_ID") or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{32}", configured) and int(configured, 16) != 0:
        return configured
    basis = f"{slug}|{github_run_id or run_id}"
    value = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]
    os.environ.setdefault("VIDEO_TRACE_ID", value)
    return value


def _span_id(trace_id: str, pid: int) -> str:
    value = hashlib.sha256(f"{trace_id}|{pid}|process-parent".encode("utf-8")).hexdigest()[:16]
    return value if int(value, 16) else "0000000000000001"


def _parse_scene_index(item: str | None) -> int | None:
    if item is None:
        return None
    match = re.search(r"(?:^|:)(\d+)$", str(item))
    return int(match.group(1)) if match else None


class _JsonLinesSpanExporter(SpanExporter):  # type: ignore[misc]
    def __init__(self, path: Path) -> None:
        self.path = path

    def export(self, spans: Any) -> Any:
        for span in spans:
            context = span.get_span_context()
            parent = getattr(span, "parent", None)
            status = getattr(span, "status", None)
            record = {
                "schema_version": SCHEMA_VERSION,
                "trace_id": f"{context.trace_id:032x}",
                "span_id": f"{context.span_id:016x}",
                "parent_span_id": f"{parent.span_id:016x}" if parent else None,
                "name": span.name,
                "kind": str(getattr(span, "kind", "internal")),
                "start_time_unix_nano": span.start_time,
                "end_time_unix_nano": span.end_time,
                "duration_s": round(max((span.end_time - span.start_time) / 1_000_000_000, 0.0), 6),
                "status": str(getattr(status, "status_code", "UNSET")),
                "status_description": getattr(status, "description", None),
                "attributes": dict(getattr(span, "attributes", {}) or {}),
                "events": [
                    {
                        "name": event.name,
                        "timestamp_unix_nano": event.timestamp,
                        "attributes": dict(event.attributes or {}),
                    }
                    for event in (getattr(span, "events", ()) or ())
                ],
                "resource": dict(getattr(getattr(span, "resource", None), "attributes", {}) or {}),
                "instrumentation_scope": getattr(
                    getattr(span, "instrumentation_scope", None), "name", None
                ),
            }
            _append_jsonl(self.path, record)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None


@dataclasses.dataclass
class StageHandle:
    name: str
    stage: str
    item: str | None
    started_ns: int
    attributes: dict[str, Any]
    span: Any = None


class TelemetrySession:
    """One process participant in a shared per-video OpenTelemetry trace."""

    def __init__(
        self,
        build_dir: str | os.PathLike[str],
        *,
        run_id: str,
        github_run_id: str | None = None,
        mode: str | None = None,
    ) -> None:
        self.build_dir = Path(build_dir).resolve()
        self.slug = self.build_dir.name
        self.run_id = run_id
        self.github_run_id = github_run_id
        self.mode = mode or "unknown"
        self.pid = os.getpid()
        self.disabled = os.environ.get("PIPELINE_TELEMETRY_DISABLED", "0") == "1"
        self.directory = self.build_dir / "telemetry"
        self.spans_path = self.directory / "spans.jsonl"
        self.metrics_path = self.directory / f"metrics-{self.pid}.json"
        self.trace_id = _trace_id(self.slug, run_id, github_run_id)
        self.started_ns = time.time_ns()
        self._finished = False
        self._lock = threading.Lock()
        self._script: dict[str, Any] | None = None
        self._metrics: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "trace_id": self.trace_id,
            "run_id": run_id,
            "github_run_id": github_run_id,
            "slug": self.slug,
            "process_id": self.pid,
            "started_at": _utc_now(),
            "stages": {},
            "events": {},
        }
        self._provider: Any = None
        self._meter_provider: Any = None
        self._tracer: Any = None
        self._root_span: Any = None
        self._root_context: Any = None
        self._stage_attempt_counter: Any = None
        self._stage_failure_counter: Any = None
        self._stage_timeout_counter: Any = None
        self._stage_duration_histogram: Any = None
        self._event_counter: Any = None
        self.otlp_configured = bool(
            os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
            or os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
            or os.environ.get("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT")
        )
        self.sdk_active = False
        self.directory.mkdir(parents=True, exist_ok=True)
        if not self.disabled:
            self._initialize_sdk()
        self._write_metrics()
        atexit.register(self.finish_run, "process_exit", None)

    def _initialize_sdk(self) -> None:
        if not OTEL_AVAILABLE:
            return
        try:
            resource = Resource.create(
                {
                    "service.name": os.environ.get("OTEL_SERVICE_NAME", SERVICE_NAME),
                    "service.version": os.environ.get("GITHUB_SHA", "local")[:40],
                    "deployment.environment.name": (
                        "github-actions" if os.environ.get("GITHUB_ACTIONS") else "local"
                    ),
                    "video.slug": self.slug,
                    "pipeline.run_id": self.run_id,
                    "github.run_id": self.github_run_id or "",
                    "github.workflow": os.environ.get("GITHUB_WORKFLOW", ""),
                    "github.job": os.environ.get("GITHUB_JOB", ""),
                    "process.pid": self.pid,
                }
            )
            provider = TracerProvider(resource=resource)
            provider.add_span_processor(SimpleSpanProcessor(_JsonLinesSpanExporter(self.spans_path)))
            if self.otlp_configured:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

                provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
            self._provider = provider
            self._tracer = provider.get_tracer("prototype_video.pipeline", "1.0")

            metric_readers = []
            if self.otlp_configured:
                from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

                metric_readers.append(
                    PeriodicExportingMetricReader(
                        OTLPMetricExporter(),
                        export_interval_millis=int(
                            os.environ.get("OTEL_METRIC_EXPORT_INTERVAL_MILLIS", "10000")
                        ),
                    )
                )
            self._meter_provider = MeterProvider(resource=resource, metric_readers=metric_readers)
            meter = self._meter_provider.get_meter("prototype_video.pipeline", "1.0")
            self._stage_attempt_counter = meter.create_counter(
                "video.pipeline.stage.attempts",
                description="Stage process attempts",
            )
            self._stage_failure_counter = meter.create_counter(
                "video.pipeline.stage.failures",
                description="Failed stage process attempts",
            )
            self._stage_timeout_counter = meter.create_counter(
                "video.pipeline.stage.timeouts",
                description="Timed-out stage process attempts",
            )
            self._stage_duration_histogram = meter.create_histogram(
                "video.pipeline.stage.duration",
                unit="s",
                description="Stage process duration",
            )
            self._event_counter = meter.create_counter(
                "video.pipeline.events",
                description="Operational Governor events",
            )

            parent_context = SpanContext(
                trace_id=int(self.trace_id, 16),
                span_id=int(_span_id(self.trace_id, self.pid), 16),
                is_remote=True,
                trace_flags=TraceFlags(TraceFlags.SAMPLED),
                trace_state=otel_trace.DEFAULT_TRACE_STATE,
            )
            parent = set_span_in_context(NonRecordingSpan(parent_context))
            self._root_span = self._tracer.start_span(
                "video.render.process",
                context=parent,
                attributes={
                    "video.slug": self.slug,
                    "pipeline.run_id": self.run_id,
                    "github.run_id": self.github_run_id or "",
                    "pipeline.mode": self.mode,
                    "process.pid": self.pid,
                    "telemetry.otlp_configured": self.otlp_configured,
                },
            )
            self._root_context = set_span_in_context(self._root_span)
            self.sdk_active = True
        except Exception as exc:
            self.sdk_active = False
            _append_jsonl(
                self.spans_path,
                {
                    "schema_version": SCHEMA_VERSION,
                    "trace_id": self.trace_id,
                    "span_id": hashlib.sha256(
                        f"{self.trace_id}|sdk-init|{self.pid}".encode("utf-8")
                    ).hexdigest()[:16],
                    "parent_span_id": None,
                    "name": "telemetry.sdk.initialization",
                    "start_time_unix_nano": self.started_ns,
                    "end_time_unix_nano": time.time_ns(),
                    "duration_s": 0.0,
                    "status": "ERROR",
                    "attributes": {
                        "video.slug": self.slug,
                        "process.pid": self.pid,
                        "exception.type": type(exc).__name__,
                        "exception.message": str(exc)[:400],
                    },
                },
            )

    def _load_script(self) -> dict[str, Any]:
        if self._script is None:
            try:
                value = json.loads((self.build_dir / "script.json").read_text(encoding="utf-8"))
                self._script = value if isinstance(value, dict) else {}
            except (OSError, ValueError, TypeError):
                self._script = {}
        return self._script

    def _scene_attributes(self, item: str | None) -> dict[str, Any]:
        index = _parse_scene_index(item)
        if index is None:
            return {}
        scenes = self._load_script().get("scenes") or []
        if index < 0 or index >= len(scenes):
            return {"video.scene.index": index}
        scene = scenes[index]
        attributes: dict[str, Any] = {
            "video.scene.index": index,
            "video.scene.number": index + 1,
            "video.scene.visual_function": str(scene.get("visual_function") or ""),
            "video.scene.symbol_family": str(scene.get("symbol_family") or ""),
            "video.scene.motion_kind": str(scene.get("motion_kind") or ""),
            "video.scene.motion_source": str(scene.get("motion_source") or ""),
            "video.scene.hero": bool(scene.get("hero")),
            "video.scene.revised": bool(scene.get("revision_note")),
        }
        provider = (
            scene.get("generation_provider")
            or scene.get("still_reference_generation_model")
            or scene.get("motion_source")
        )
        if provider:
            attributes["gen_ai.provider.name"] = str(provider)
        model = scene.get("generation_model") or scene.get("model")
        if model:
            attributes["gen_ai.request.model"] = str(model)
        workflow = scene.get("comfy_workflow") or scene.get("workflow")
        if workflow:
            attributes["video.generation.workflow"] = str(workflow)
        if scene.get("seed") is not None:
            attributes["video.generation.seed"] = str(scene.get("seed"))
        prompt = str(scene.get("image_prompt") or scene.get("query") or "").strip()
        if prompt:
            attributes["video.prompt.sha256"] = hashlib.sha256(
                prompt.encode("utf-8")
            ).hexdigest()
        for key, target in (
            ("credits_used", "video.credits.used"),
            ("cost_usd", "video.cost.usd"),
            ("visual_risk_score", "video.visual_risk.score"),
        ):
            try:
                if scene.get(key) is not None:
                    attributes[target] = float(scene[key])
            except (TypeError, ValueError):
                continue
        return attributes

    def start_stage(
        self,
        *,
        stage: str,
        item: str | None,
        label: str,
        attributes: Mapping[str, Any] | None = None,
    ) -> StageHandle:
        attrs = {
            "video.slug": self.slug,
            "pipeline.run_id": self.run_id,
            "pipeline.stage": stage,
            "pipeline.stage.item": item or "",
            "pipeline.stage.label": label,
            "process.pid": self.pid,
            **self._scene_attributes(item),
            **dict(attributes or {}),
        }
        span = None
        if self.sdk_active and self._tracer is not None:
            try:
                span = self._tracer.start_span(
                    f"video.stage.{stage}",
                    context=self._root_context,
                    attributes=_json_safe(attrs),
                )
            except Exception:
                span = None
        return StageHandle(
            name=f"video.stage.{stage}",
            stage=stage,
            item=item,
            started_ns=time.time_ns(),
            attributes=attrs,
            span=span,
        )

    def finish_stage(
        self,
        handle: StageHandle,
        *,
        status: str,
        returncode: int,
        duration_s: float,
        timed_out: bool = False,
        failure_class: str | None = None,
        fingerprint: str | None = None,
        made_progress: bool | None = None,
        artifact_after: Mapping[str, Any] | None = None,
    ) -> None:
        attrs = {
            "pipeline.stage.status": status,
            "process.exit.code": returncode,
            "pipeline.stage.duration_seconds": round(float(duration_s), 6),
            "pipeline.stage.timed_out": bool(timed_out),
            "pipeline.failure.class": failure_class or "",
            "pipeline.failure.fingerprint": fingerprint or "",
            "pipeline.made_progress": bool(made_progress),
        }
        if artifact_after:
            attrs.update(
                {
                    "pipeline.artifact.count": int(artifact_after.get("count") or 0),
                    "pipeline.artifact.bytes": int(artifact_after.get("bytes") or 0),
                    "pipeline.artifact.digest": str(artifact_after.get("digest") or ""),
                }
            )
        if handle.span is not None:
            try:
                for key, value in attrs.items():
                    handle.span.set_attribute(key, value)
                if returncode != 0:
                    handle.span.set_status(
                        Status(
                            StatusCode.ERROR,
                            f"{status}: {failure_class or 'stage failure'}",
                        )
                    )
                else:
                    handle.span.set_status(Status(StatusCode.OK))
                handle.span.end()
            except Exception:
                pass
        else:
            end_ns = time.time_ns()
            _append_jsonl(
                self.spans_path,
                {
                    "schema_version": SCHEMA_VERSION,
                    "trace_id": self.trace_id,
                    "span_id": hashlib.sha256(
                        f"{self.trace_id}|{handle.started_ns}|{handle.name}|{self.pid}".encode(
                            "utf-8"
                        )
                    ).hexdigest()[:16],
                    "parent_span_id": _span_id(self.trace_id, self.pid),
                    "name": handle.name,
                    "start_time_unix_nano": handle.started_ns,
                    "end_time_unix_nano": end_ns,
                    "duration_s": round(max((end_ns - handle.started_ns) / 1e9, 0.0), 6),
                    "status": "ERROR" if returncode else "OK",
                    "attributes": {**handle.attributes, **attrs},
                    "resource": {"service.name": SERVICE_NAME},
                },
            )

        metric_attrs = {
            "video.slug": self.slug,
            "pipeline.stage": handle.stage,
            "pipeline.stage.status": status,
        }
        try:
            if self._stage_attempt_counter:
                self._stage_attempt_counter.add(1, metric_attrs)
            if self._stage_duration_histogram:
                self._stage_duration_histogram.record(float(duration_s), metric_attrs)
            if returncode != 0 and self._stage_failure_counter:
                self._stage_failure_counter.add(1, metric_attrs)
            if timed_out and self._stage_timeout_counter:
                self._stage_timeout_counter.add(1, metric_attrs)
        except Exception:
            pass
        with self._lock:
            bucket = self._metrics["stages"].setdefault(
                handle.stage,
                {
                    "attempts": 0,
                    "successes": 0,
                    "failures": 0,
                    "timeouts": 0,
                    "total_duration_s": 0.0,
                    "duration_samples_s": [],
                },
            )
            bucket["attempts"] += 1
            bucket["successes" if returncode == 0 else "failures"] += 1
            bucket["timeouts"] += int(bool(timed_out))
            bucket["total_duration_s"] = round(
                float(bucket["total_duration_s"]) + float(duration_s), 6
            )
            bucket["duration_samples_s"].append(round(float(duration_s), 6))
        self._write_metrics()

    def add_event(self, event: str, payload: Mapping[str, Any]) -> None:
        if self.disabled:
            return
        if event == "heartbeat" and os.environ.get("OTEL_INCLUDE_HEARTBEATS", "0") != "1":
            return
        if event not in IMPORTANT_EVENTS and not event.startswith("quality_"):
            return
        attrs = {
            "video.slug": self.slug,
            "pipeline.event": event,
            **{
                f"pipeline.event.{key}": value
                for key, value in payload.items()
                if isinstance(value, (str, int, float, bool)) and key not in {"command"}
            },
        }
        try:
            if self._root_span is not None:
                self._root_span.add_event(event, _json_safe(attrs))
            if self._event_counter:
                self._event_counter.add(
                    1,
                    {
                        "video.slug": self.slug,
                        "pipeline.event": event,
                    },
                )
        except Exception:
            pass
        with self._lock:
            self._metrics["events"][event] = int(self._metrics["events"].get(event, 0)) + 1
        self._write_metrics()

    def _write_metrics(self) -> None:
        payload = dict(self._metrics)
        payload.update(
            {
                "updated_at": _utc_now(),
                "sdk_active": self.sdk_active,
                "otlp_configured": self.otlp_configured,
            }
        )
        _atomic_json(self.metrics_path, payload)

    def finish_run(
        self,
        status: str = "process_exit",
        summary: Mapping[str, Any] | None = None,
    ) -> None:
        if self._finished:
            return
        self._finished = True
        ended_ns = time.time_ns()
        if self._root_span is not None:
            try:
                self._root_span.set_attribute("pipeline.run.status", status)
                self._root_span.set_attribute(
                    "pipeline.run.duration_seconds",
                    round(max((ended_ns - self.started_ns) / 1e9, 0.0), 6),
                )
                if summary:
                    self._root_span.set_attribute(
                        "pipeline.run.passes", int(summary.get("passes") or 0)
                    )
                    self._root_span.set_attribute(
                        "pipeline.run.incident_count",
                        len(summary.get("incidents") or []),
                    )
                if status not in {"done", "success", "process_exit"}:
                    self._root_span.set_status(Status(StatusCode.ERROR, status))
                else:
                    self._root_span.set_status(Status(StatusCode.OK))
                self._root_span.end()
            except Exception:
                pass
        elif not self.disabled:
            _append_jsonl(
                self.spans_path,
                {
                    "schema_version": SCHEMA_VERSION,
                    "trace_id": self.trace_id,
                    "span_id": _span_id(self.trace_id, self.pid),
                    "parent_span_id": None,
                    "name": "video.render.process",
                    "start_time_unix_nano": self.started_ns,
                    "end_time_unix_nano": ended_ns,
                    "duration_s": round(max((ended_ns - self.started_ns) / 1e9, 0.0), 6),
                    "status": "ERROR" if status not in {"done", "success", "process_exit"} else "OK",
                    "attributes": {
                        "video.slug": self.slug,
                        "pipeline.run_id": self.run_id,
                        "github.run_id": self.github_run_id or "",
                        "pipeline.mode": self.mode,
                        "pipeline.run.status": status,
                        "process.pid": self.pid,
                    },
                    "resource": {"service.name": SERVICE_NAME},
                },
            )
        self._metrics["finished_at"] = _utc_now()
        self._metrics["status"] = status
        self._write_metrics()
        try:
            if self._provider is not None:
                self._provider.force_flush(timeout_millis=5000)
                self._provider.shutdown()
            if self._meter_provider is not None:
                self._meter_provider.force_flush(timeout_millis=5000)
                self._meter_provider.shutdown()
        except Exception:
            pass


def create_session(
    build_dir: str | os.PathLike[str],
    *,
    run_id: str,
    github_run_id: str | None = None,
    mode: str | None = None,
) -> TelemetrySession:
    return TelemetrySession(
        build_dir,
        run_id=run_id,
        github_run_id=github_run_id,
        mode=mode,
    )
