# Animation profiles

Animation quality is selected independently from the recurring-character profile.
Use the top-level `animation_profile` field in `build/<slug>/script.json`.

## 1. Regular Tier 1 animated

```json
{
  "animation_profile": "animated_tier1"
}
```

Use for premium consciousness, belief-analysis, perception, memory, identity,
emotion, time, or other concept films.

The contract enforces:

- premium cinematic symbolic motion design
- one ruling visual system and one strong symbol per beat
- at least 80% genuine temporal footage by duration
- no more than 20% still-derived footage, including animated stills
- human-heavy scenes below 45%
- minimal keyword captions rather than paragraph text
- cinematic push-ins, orbits, motivated depth, material physics, and connected transitions
- no template explainer graphics, flat icon language, childish cartoon treatment, or slideshow zooms

## 2. Tier 1 June Oxley animated

```json
{
  "profile": "june_oxley",
  "animation_profile": "june_oxley_animated_tier1"
}
```

Use for premium June Oxley episodes with high-end stylized character animation,
cinematic acting, recurring town continuity, and poetic ordinary-to-surreal turns.

The contract enforces:

- `profile: june_oxley`
- character reference lock `june_oxley_v1`
- the same original June face, age, hair, beard, build, and workwear in every scene
- at least 80% genuine temporal footage
- no more than 20% still-derived footage
- recurring porch, diner, feed store, bait shop, garage, gravel road, water tower, and moonshine-shed world
- expressive but grounded acting: rocking-chair rhythm, hat and hand gestures, chuckling pauses
- warm cinematic lighting and tactile weathered materials
- no meme-grandpa style, cheap cartoon treatment, face drift, politics, or permanent joke banner

The voice remains controlled by the June Oxley character bible. The exact ElevenLabs
voice ID for `Granpa Spuds Oxley` must be resolved before a new June render; the
pipeline must never silently substitute Liam.

## 3. Regular June Oxley animated

```json
{
  "profile": "june_oxley",
  "animation_profile": "june_oxley_animated_standard"
}
```

Use for efficient recurring episodes that remain polished and consistent without
the full cinematic cost of Tier 1.

The contract enforces:

- stable `june_oxley_v1` character continuity
- polished stylized 2D or 2.5D design
- at least 70% genuine temporal footage
- no more than 30% still-derived footage
- clean medium shots, restrained push-ins and pans, expressive gestures, and light background motion
- warm recurring town locations and simple symbolic inserts
- no low-grade templates, random stock-grandpa faces, childish style, or paragraph captions

## What the preflight writes

The governed production entrypoint resolves aliases and persists a complete
machine-readable contract before voice, stock, hero generation, or motion work:

- `animation_contract_version`
- `animation_quality_tier`
- `animation_source_priority`
- `animation_camera_language`
- `animation_design_language`
- `animation_character_reference_id` when applicable
- `minimum_true_motion_ratio`
- `max_still_source_ratio`
- per-scene `animation_query`, source preference, camera language, and design language

The original literal query is preserved in `animation_base_query`. The styled query
becomes the actual acquisition query, so the selected mode changes real media
selection instead of serving as documentation only.

## Standing boundaries

Animation profiles may shape visual planning, prompts, footage selection, motion
budgets, captions, and character continuity. They may not:

- rewrite approved narration
- weaken science-fidelity labels
- remove grounding or the open invitation
- create render requests autonomously
- change the June Oxley voice or political boundary
- classify an animated still as genuine temporal footage

Videos without `animation_profile` remain unchanged.
