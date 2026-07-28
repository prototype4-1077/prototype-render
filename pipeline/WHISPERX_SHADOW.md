# WhisperX Shadow Alignment Challenger

WhisperX is evaluated as a challenger. It is not the production aligner.

## Safety boundary

The shadow workflow may read:

- `script.json`;
- `vo.mp3`;
- current `words.json`;
- the scene timing already stored in the script;
- an optional human-reviewed `alignment-reference.json`.

It may write only:

- `alignment-challenger.json` — compact comparison metrics;
- `alignment-challenger-words.json` — full WhisperX word timings for artifact review;
- the aggregate benchmark ledger.

It must not edit `script.json`, `words.json`, captions, overlays, scene durations,
OTIO media references, or rendered files.

## Runtime configuration

The isolated shadow environment is pinned in `requirements-whisperx.txt`.
Defaults are deliberately small enough for a GitHub-hosted CPU runner:

```text
WHISPERX_MODEL=base.en
WHISPERX_DEVICE=cpu
WHISPERX_COMPUTE_TYPE=int8
WHISPERX_BATCH_SIZE=4
WHISPERX_LANGUAGE=en
```

The workflow does not run diarization. Liam's narration is a single-speaker track,
and diarization would add cost and another source of error without helping caption timing.

## What the report measures

For both the production `faster-whisper` words and the WhisperX challenger:

- transcript word error rate against the exact script;
- script-word coverage;
- coverage of contractions and tokens containing numbers;
- error between observed first-word timing and each planned scene start;
- error between the last recognized word and the planned scene end;
- optional word-start error against a manual timing reference.

It also records word-by-word start-time disagreement between the two systems.
Disagreement alone does not establish that either system is correct.

Generated ElevenLabs videos use their existing scene alignment as a scene-level
reference. User-supplied narration is labeled `current_pipeline_scene_timing`, not
independent ground truth.

## Optional manual timing reference

For a small set of benchmark videos, add:

```json
{
  "schema_version": 1,
  "reviewed_by": "James",
  "reviewed_at": "2026-07-23T00:00:00Z",
  "words": [
    {"w": "Anxiety", "s": 0.42, "e": 0.86},
    {"w": "often", "s": 0.88, "e": 1.12}
  ]
}
```

Save it as `build/<slug>/alignment-reference.json`. Partial references are allowed;
only words that can be matched to the script are scored.

## Promotion gate

`whisperx_benchmark_ledger.py` requires all of the following before it can say the
challenger is eligible for a human promotion decision:

- at least 20 successful shadow runs;
- at least 5 runs with manually reviewed word timing;
- shadow failure rate at or below 5%;
- median script-word coverage no more than 0.5 percentage points below production;
- at least 30 ms median improvement against the manual references.

Even when every check passes, promotion is not automatic. A separate reviewed change
would be required to alter production alignment.

## Commands

```bash
pip install -r pipeline/requirements-whisperx.txt
python3 pipeline/whisperx_challenger.py build/<slug> --non-blocking
python3 pipeline/whisperx_benchmark_ledger.py .
```

For deterministic tests or replaying an archived WhisperX result:

```bash
python3 pipeline/whisperx_challenger.py build/<slug> \
  --raw-result pipeline/tests/fixtures/whisperx-result.json
```
