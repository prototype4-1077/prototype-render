# OpenTelemetry Render Tracing

This layer adds vendor-neutral traces and metrics around the existing Pipeline Governor.
It does not replace the Governor, its JSONL flight recorder, its timeout policy, the
quality firewall, or James's approval process.

OpenTelemetry Python traces and metrics are stable signals. This implementation does not
use the OpenTelemetry logs signal.

## Default behavior

Every Governor process participating in one video render shares one deterministic
32-character trace ID. The first Governor process sets `VIDEO_TRACE_ID`; child processes
inherit it through the environment.

Each process creates a `video.render.process` span. Every supervised subprocess creates a
child span named:

```text
video.stage.<stage>
```

Examples include:

```text
video.stage.tts
video.stage.transcribe
video.stage.footage
video.stage.hero
video.stage.assemble
video.stage.quality
```

The instrumentation records:

- video slug and Governor run ID;
- GitHub workflow, job, run, and commit when available;
- process ID;
- stage, scene index, status, duration, exit code, and timeout state;
- retry, remediation, timeout-extension, circuit-breaker, and quality events;
- artifact count, byte total, and digest after each stage;
- provider, model, workflow, seed, visual function, symbol family, hero/revision status;
- optional credits, cost, and visual-risk values when the scene metadata contains them.

Prompts are not recorded. A SHA-256 prompt identity is recorded so identical and changed
prompt versions can be compared without storing the wording.

## Local evidence

Telemetry is written under:

```text
build/<slug>/governor/telemetry/
```

`build/<slug>/telemetry` is a stable symlink used by local tools.

Files include:

- `spans.jsonl` — completed spans from every Governor process;
- `metrics-<pid>.json` — crash-resilient per-process stage and event counters;
- `telemetry-summary.json` — consolidated stage, scene, failure, cost, and latency report.

The existing Governor diagnostics artifact already uploads `governor/**`, so full traces
require no change to the proven render workflow. `telemetry-post-render.yml` downloads
that artifact, creates the compact summary, uploads a 90-day telemetry artifact, attaches
the summary to a successful video's Release, and commits only the compact summary.

## Optional OTLP/HTTP export

Local JSONL is always the fallback. When one of the standard OTLP endpoint variables is
present, spans and metrics are additionally exported over OTLP/HTTP:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318
```

Signal-specific endpoints are also supported:

```bash
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://collector:4318/v1/traces
export OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=http://collector:4318/v1/metrics
```

Authentication can use the standard OpenTelemetry exporter header environment variables.
Secrets are never copied into local telemetry attributes.

No observability backend is required. The repository remains vendor-neutral.

## Failure isolation

Telemetry is intentionally non-authoritative:

- SDK import failure falls back to local spans;
- OTLP connection failure cannot fail a rendering stage;
- telemetry exceptions are swallowed at the Governor boundary;
- disabling telemetry does not change Governor behavior;
- render delivery still depends only on the established quality and output checks.

To disable the layer entirely:

```bash
export PIPELINE_TELEMETRY_DISABLED=1
```

Heartbeats are not copied into OpenTelemetry by default because they are high volume.
They can be included for a temporary investigation:

```bash
export OTEL_INCLUDE_HEARTBEATS=1
```

## Reports

Create or rebuild a compact summary with:

```bash
python3 pipeline/telemetry_report.py build/<slug> --require-spans
```

The report shows:

- whether the render emitted exactly one trace ID;
- stage attempts, successes, failures, timeouts, p50, p95, and total duration;
- slowest stages;
- scene-level provider/model/workflow timing;
- failure fingerprints;
- retry and remediation event counts;
- available credit/cost totals;
- privacy assertions and evidence-driven recommendations.

## Configuration boundary

This implementation uses manual instrumentation rather than automatic instrumentation.
That keeps the span vocabulary aligned with the pipeline's real editorial stages instead
of producing a large collection of low-value library spans.

OpenTelemetry can show where time, failure, retries, credits, and revisions accumulate.
It cannot decide that a faster result is a better video. Any optimization suggested by a
trace must still pass the existing champion/challenger quality checks and James's review.
