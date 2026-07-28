# Eleven v3 narration

The default narrator is **Liam — Energetic, Social Media Creator** (`TX3LPaxmHKxFdv7VOQHJ`) using model `eleven_v3`.

The pipeline runs in the **Creative** stability mode by default:

```json
{
  "elevenlabs_model": "eleven_v3",
  "elevenlabs_stability_mode": "creative",
  "voice_settings": {
    "similarity_boost": 0.75,
    "speed": 0.91
  }
}
```

For Eleven v3, the named stability modes map to:

| Mode | Stability | Use |
|---|---:|---|
| `creative` | `0.0` | Maximum expression and tag responsiveness; pipeline default |
| `natural` | `0.5` | Balanced delivery |
| `robust` | `1.0` | Most consistent, least responsive to tags |

`style` is held at `0.0` for v3. Delivery direction comes from audio tags.

## Scene audio tags

Put tags in `audio_tags`, never inside the captioned narration text:

```json
{
  "text": "What if the thing watching your life is also the thing creating it?",
  "audio_tags": ["curious"]
}
```

Use `[]` for a deliberately neutral scene. Use no more than one tag for most scenes. Useful vocal directions include `curious`, `thoughtful`, `excited`, `dramatic`, `firm`, `tense`, `calm`, `softly`, `low voice`, `whispers`, `sighs`, `sarcastic`, `mischievously`, and `laughs`.

## Opening delivery

Choose scene 0 from the mood and message of the complete script. An opener may use laughter, low voice, thoughtful reflection, sarcasm, curiosity, excitement, drama, mischievousness, whispers, or neutral delivery.

Never default every video to a whisper or curious hook. Laughter requires a genuine joke. Whispers require intimacy, secrecy, or quiet wonder. Low voice should support gravity or mystery. When no delivery clearly fits, keep the opener neutral.

For older scripts without `audio_tags`, the runtime no longer assigns a fixed tone merely because a scene is first. An optional `opening_mood`, `delivery_mood`, or `tone` field can select the opener; otherwise a plain opening remains neutral, a real question can become curious, and transformation beats can become excited.

## Approved expressive-performance requirement

The minimum reference is **Maybe the Knob Isn't Broken**, render run `29606656473`.

Every newly generated Liam performance must have a deliberate emotional contour across the full script. Include clear energetic lifts, quiet or intimate lows, natural pauses, changes in intensity, and neutral beats that create contrast. Use laughter selectively only when the writing contains a genuine comedic moment. Do not force every available tag into every script, and do not make the delivery constantly exaggerated.

Performance directions are metadata only. They must never appear inside scene `text`, captions, titles, subtitles, or any other visible graphic. The approved spoken words must remain unchanged.

Older scripts without `audio_tags` still receive conservative context-based fallbacks for questions, transformations, and quiet closers. Set `"auto_audio_tags": false` to disable all fallback tags, or use `"audio_tags": []` on one scene to keep that beat neutral.

The narration request writes effective non-secret settings to `voiceover_config` in `script.json` and to `voiceover-manifest.json`. The API key is read only from `ELEVENLABS_API_KEY`; it must never be committed.
