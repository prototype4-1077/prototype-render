# Video Pipeline Governor

The Governor is an operational control layer around the existing resumable video builder. It does **not** replace or modify `learn.py`; creative taste learning remains separate from production reliability learning.

## What changes

CI now runs:

```bash
python3 pipeline/run_governed.py build/<slug>
```

instead of calling `build.py` in an unbounded shell loop. `governed_build.py` imports the existing builder and replaces only its subprocess helper with `PipelineGovernor.run`. Every existing build stage, script format, checkpoint, and creative-quality rule remains in place.

## Closed-loop behavior

For every subprocess, the Governor:

1. Classifies the stage (`tts`, `transcribe`, `footage`, `hero`, `motion`, `assemble`, and so on).
2. Records a structured start event, policy, command fingerprint, and artifact snapshot.
3. Emits heartbeats containing elapsed time, idle time, output growth, and artifact growth.
4. Extends a soft deadline only while useful progress is visible.
5. Terminates the entire process group at a learned stall limit or absolute hard limit.
6. Quarantines incomplete media/JSON instead of letting a later pass mistake it for a valid checkpoint.
7. Retries only transient or unknown failures, with a strict per-fingerprint budget.
8. Opens a circuit breaker when the same no-progress state or failure repeats.
9. Resumes from all valid artifacts already produced by `build.py`.
10. Runs an independent technical quality firewall before declaring the render complete.

## Quality authority

`quality_gate.py` blocks delivery when a required output is missing, corrupt, undecodable, undersized, incorrectly oriented, missing audio, below the resolution/frame-rate floor, or materially out of sync with the timed script.

The deep gate fully decodes deliverables with FFmpeg. Long black, frozen, or silent intervals are reported for review; high-confidence structural failures are blocking. Speed-oriented tuning never overrides these checks.

Editorial curation reels are recognized separately and are not required to contain a YouTube render or audio track.

## Operational learning

Each finished or failed run writes:

- `build/<slug>/governor/events.jsonl` — detailed flight recorder (uploaded as a workflow artifact, not committed)
- `build/<slug>/governor/current.json` — live stage and heartbeat state
- `build/<slug>/governor-summary.json` — compact committed run history
- `build/<slug>/render-status.json` — current/outcome state for humans and automation
- `build/<slug>/quality_report.json` — independent output acceptance report
- `build/<slug>/governor-review.json` — cross-run bottlenecks and recurring incident recommendations

Future runs scan prior committed summaries. After at least five successful observations of a stage, its soft timeout becomes:

```text
clamp(3 × historical p95 + 30 seconds, stage safety floor, 85% of hard limit)
```

This lets the pipeline stop abnormal waits earlier without learning from failures or shrinking below a conservative floor. Absolute hard limits remain fixed in code.

Failure messages are normalized and secret-redacted before hashing into stable fingerprints. The report ranks recurring fingerprints, timeout rates, tail-latency stages, and quality codes instead of optimizing whichever error happened most recently.

## Runtime modes

Set `GOVERNOR_MODE` to:

- `observe` — fixed conservative policies; still records telemetry and enforces explicit workflow limits.
- `recover` — default; applies history-derived bounded timeouts, quarantine, retries, and circuit breakers.
- `tune` — currently equivalent to `recover` for timeout learning and reserved for future champion/challenger policies.

Other controls:

```bash
GOVERNOR_HEARTBEAT_SECONDS=15
GOVERNOR_CONSOLE_HEARTBEATS=1
```

## Useful commands

Run the governed pipeline locally:

```bash
python3 pipeline/run_governed.py build/<slug> --overall-timeout 4680
```

Run only the independent gate:

```bash
python3 pipeline/quality_gate.py build/<slug>
```

Review accumulated operational evidence:

```bash
python3 pipeline/governor_report.py
python3 pipeline/governor_report.py --json --output governor-review.json
```

Run regression tests:

```bash
python3 -m unittest discover -s pipeline/tests -v
```

## Failure states

`render-status.json` and `governor-summary.json` use explicit terminal states:

- `done`
- `quality_failed`
- `failed`
- `stalled`
- `overall_timeout`
- `pass_limit`

A failed run still uploads detailed diagnostics and commits its compact summary/status when GitHub permits the final telemetry push. This makes failures inspectable rather than disappearing at the failed workflow step.

## Rollback

The integration is intentionally narrow. To disable the Governor without changing the creative pipeline, change the workflow build command back to the previous repeated invocation of `pipeline/build.py`. Existing build artifacts and `learn.py` memory remain compatible.
