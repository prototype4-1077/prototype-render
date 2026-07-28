# Photoreal Still Doctrine — "a photograph of the impossible"

Standing art direction (Jul 2026, James): generated hero stills must read as
REAL — an actual photo of a real person, place, or thing — while keeping the
mythical touch. Deep 3D presence; truly cinematic.

## The two rules

**1. Documentary magical realism.** 90% of the frame is a believable photograph:
real textures, real light behavior, film grain, small imperfections (wet wood,
worn fabric, dust on glass). Exactly ONE impossible element — and it is
photographed as physically present, lit by the same light as everything else
(a net full of stars underlights the fisherman's coat; a kettle's galaxy casts
glow on real tiles). If the impossible element doesn't illuminate or touch its
surroundings, it reads as a composite and dies.

**2. Three-plane depth, always.** Every prompt names all three planes:
- NEAR: a real out-of-focus occluder cutting the frame (rope, doorframe,
  lantern, shoulder)
- MID: the subject, sharp
- FAR: distance dissolving into haze/mist/darkness (atmospheric perspective)
This is what the 2.5D multiplane engine (motion.py) needs to make the still
move like deep 3D — dolly-zoom, orbit, push-in, rack-focus.

## Prompt vocabulary
USE: cinematic 35mm film still · anamorphic lens · shallow depth of field ·
motivated single light source · film grain · muted filmic grade · atmospheric
haze · natural skin/surface texture · documentary framing.
BAN: "digital art", "hyperdetailed", "ethereal glow everything", perfect
symmetry, oversaturation, floating particles everywhere, "artstation".

## Palette
Variety rule still stands: palette derives from each story. Photoreal does not
mean desaturated-teal-always — a story can be golden-hour, neon-night, candle
amber, storm blue. It must simply look like FILM, not render.

## Where the old painted style still applies
DMT trance beats (mandala/fractal slides per DMT_STYLE.md) keep their stylized
aura — that lane is deliberately non-photographic. DMT real-world grounding
shots (the room, the return, the couch) go photoreal like everything else.

## The motion side (motion.py multiplane-v1)
Depth is estimated, edge-refined (guided filter), split into bg/mid/near with
inpainted disocclusions, then moved with per-plane differentials:
push_in · dolly_zoom (vertigo) · orbit · rack_focus · lateral — chosen
per-scene (deterministic seed), all with handheld micro-sway and depth-aware
dust between planes. camera= can be forced per call.
