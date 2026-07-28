# Protected User Script Intake

This path is for scripts supplied directly by James. It packages and validates the script without rewriting the spoken narration and without starting a render. **User-script intake never starts a render.**

## Required files

Create one isolated build directory:

```text
build/<slug>/source-script.txt
build/<slug>/intake.request
```

`source-script.txt` is the authoritative raw script. `intake.request` contains:

```text
go
```

An optional `submission.json` may declare production choices:

```json
{
  "title": "My Title",
  "target_scenes": 24,
  "title_mode": "standalone",
  "series_label": null,
  "profile": null,
  "animation_profile": null,
  "science_fidelity": "metaphor",
  "render_outputs": ["youtube"],
  "performance_tag_policy": "extract"
}
```

For June Oxley, set `profile` to `june_oxley`; preflight supplies the canonical Spuds voice and blocks a conflicting voice. For a regular Liam video, the intake uses the canonical Liam voice unless an explicit voice is supplied.

## Performance directions

Recognized bracketed directions such as `[long pause]`, `[whisper]`, and `[chuckles]` require an explicit policy:

- `extract` keeps them out of spoken narration and captions and stores them as audio-direction metadata.
- `preserve` treats the brackets as literal spoken text.

The intake blocks rather than guessing.

## Guarantees

- Spoken words, capitalization, apostrophes, dashes, and punctuation are checked against an authoritative source fingerprint.
- Scene boundaries may change whitespace only; they may not change the spoken text.
- Existing non-intake `script.json` packages are never overwritten.
- Intake does not create `render.request` or start a render.
- The standard scene count is 24 unless an explicit alternative is requested.
- Short scripts are valid and do not require a 60-second voiceover.
- The render dispatcher rechecks the source lock after safe preflight normalization and before package fingerprinting.
- A package edit after preflight causes the render job to reject the package fingerprint.
- The regression suite proves a representative plain-text submission passes the same production preflight used by real renders.

## Results

The workflow writes:

```text
source-spoken.txt
script.json
intake-report.json
preflight-report.json
package-fingerprint.json
intake-ready.txt      # package passed; render has not started
```

or:

```text
intake-blocked.txt
```

A render begins only after a separate, explicit `build/<slug>/render.request` is committed.
