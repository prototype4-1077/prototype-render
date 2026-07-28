# James's TikTok Style Profile
Extracted from "The Collective Tilt" and "Field to Point Synchronization" (Dec 2025).

## Format
- Current default: one 1920x1080 (16:9 regular YouTube) video, 30fps, H.264 + AAC.
  Portrait and short versions are created only when James explicitly requests them.
- Stock b-roll clips, one per sentence/beat (~6-9s each), scene cut on sentence boundary
- Footage look: heavily defocused / shallow DOF / blurred motion; moody interiors, anonymous crowds,
  abstract 3D renders (white figure + red question mark), minimal white scenes, dark tech/red-code frames.
  Faces rarely in focus. Eerie-calm, liminal feel.

## Title card
- Handwritten marker-style font, white with soft black shadow, very large, stacked words
  (e.g. "The / Collective / Tilt"), centered, shown over opening clip for first ~8s alongside first caption.
- Permanent title wrapping rule: use at most two words on a line. A line may contain three words only
  when at least one is a short connector or function word such as "I", "a", "the", "on", "of", or "to".

## Captions
- Sentence/phrase-level blocks (2-4 lines max, ~34 chars/line), not word-by-word pop
- Thin geometric sans (Questrial/Century-Gothic-like), white, ~42px
- Each line sits in its own semi-transparent dark gray box (#3a3a3a @ ~75%), centered, lower third (block center ~y=920)
- 2-4 key words per sentence highlighted pale yellow (#e6e87e): the conceptual load-bearing words
  (e.g. "collective", "plot twist", "habit", "inherited", "downloaded", "spell", "thinning")

## Audio
- Calm, measured, intimate voiceover; slow pace with deliberate pauses ("just... fail to convince.")
- Ambient/atmospheric music bed underneath, low in the mix

## Writing voice
- Second-person philosophical monologue: consciousness, the collective, conditioning, awakening
- Conversational hook opener: "You ever notice how..."
- Software/tech metaphors throughout: "running code that isn't theirs", "programs you never wrote",
  "reactions aren't personal — they're inherited. downloaded.", "the only thing that actually computes",
  "running side by side without fully syncing", "You see frames."
- Rhetorical questions as pivots: "Who taught me to fear this?" "Why does this reaction feel older than me?"
- Quoted inner dialogue: '"No, that's too expensive. I'm not carrying that anymore."'
- Short declaratives for punch: "The spell is thinning." "It's the field itself recalibrating."
- Contrast pairs: "Not with a manifesto, but with a breath. Not with a protest, but with a choice."
  "The personal becomes transparent. The impersonal becomes intimate."
- Em-dashes and trailing builds; one-word caption beats for emphasis: "discernment." "downloaded."
- Arc: hook (relatable observation) → diagnosis (old narratives/conditioning loosening) → mechanism
  (inherited programs, the field) → turn (choice/awareness) → quiet revelation ending, often an identity
  statement: "I AM the field experiencing a point of contact." / "one orientation. one you."

## Reference script fragments (The Collective Tilt)
"You ever notice how the collective feels like it just hit that moment in a movie where the plot twist
isn't loud, it's obvious? Like everybody suddenly realizes the story they were defending was held
together by habit, not clarity. That's the era we're standing in. Because something subtle but
unmistakable is happening. The old narratives, the identities wrapped in fear and passed down like
family heirlooms — they're starting to loosen. [...] It's like the collective walked back into the
store of old beliefs, 'No, that's too expensive. I'm not carrying that anymore.' A certain kind of
tired is spreading. [...] The fatigue that shows up when you finally recognize how much of your
emotional bandwidth was being drained by programs you never wrote. And when people get tired of
running code that isn't theirs, they stop performing the version of themselves that the past demanded.
They start asking sharper questions. Who taught me to fear this? Why does this reaction feel older
than me? See, this movement isn't about a particular group waking up. It's the field itself
recalibrating. Like clarity diffusing through the room [...] People are beginning to recognize when
their reactions aren't personal — they're inherited. downloaded. [...] you get to decide whether to
keep running it. That's why the noise feels louder lately. It's not growing — The spell is thinning.
And unity — not the kumbaya kind, the structural, lived, grounded kind — is starting to feel like the
only thing that actually computes. And in that space between the old story and the new one not yet
named — that's where the realignment happens. Not with a manifesto, but with a breath. Not with a
protest, but with a choice. The next move isn't to build a new system. It's to remember you are the
source. It's waiting for you to consciously meet it there."

## v2 visual spec (July 2026, per "How Reality Works" reference)
- Letterboxed: 16:9 footage band centered on black 1080x1080; captions live in the bottom black band.
- Footage shifted from plain mood b-roll to idea-bearing symbols: keyholes, printed truth, arrows,
  eyes, doors, question marks, inverted worlds, letters, recursive rings, lenses, maps, crowds,
  and human explorers. Surreal/mystical imagery remains available, but the symbol must explain
  the spoken mechanism and the sequence must not collapse into one repeated visual shorthand.
- Title: bold rounded ALL-CAPS (Baloo 2 ExtraBold), white w/ shadow, over the opening visual
  (replaces handwritten Caveat, which was the v1 square-layout look).

## v4 (July 2026): format is 1080x1920 (9:16 phone/TikTok full-screen)
- Same letterbox grammar: 16:9 footage band vertically centered on black, title over the band,
  captions ~y1430 (clear of TikTok UI). All future videos in 9:16.

## v16 still-photo treatment (July 2026)
- Default generated still/hero slides should look like natural documentary photographs that belong
  beside the surrounding stock footage: candid contemporary people, practical locations, ordinary
  clothing, realistic skin, neutral color, and soft readable daylight.
- Acquire and select the genuine stock-video scenes first. Before generating a still, choose the
  closest related selected stock scene by spoken mechanism, symbol family, physical prop, and
  timeline proximity. Save its public stock-video frame and use that exact frame as the
  image-to-image reference—not merely as words appended to a prompt.
- The reference transfers camera language, lens perspective, readable exposure, practical lighting,
  palette, depth, and production realism. The requested subject/action still replaces the reference
  content, faces, text, signage, and logos as needed. This creates continuity without cloning a shot.
- Every permitted still receives the complete appropriate enhancement path: reference-conditioned
  generation or reference harmonization, natural exposure/detail recovery, depth-separated layers,
  occlusion/background completion, restrained recipe-specific internal motion, practical-light
  movement, the film-wide grade, and subtle grain. Never leave a raw still or pan/zoom-only slide.
- Supplied stills and keyframes are preserved; the pipeline creates enhanced derivatives. If a
  generated still cannot obtain or use a valid stock frame, fall back to genuine stock footage.
- `still_reference_report.json` records the selected reference scene/frame, semantic match score,
  and every enhancement applied. Reference-conditioned stills remain fully counted inside the
  35% still-source ceiling.
- Do not use gold fog, volumetric haze, backlit silhouettes, visible auras, fantasy particles, or
  stiff theatrical staging as the default visual shorthand. Reserve surreal treatment for an
  explicitly visionary/DMT concept.
- When the body itself carries the idea, convey inner states through believable posture, gaze,
  distance, and room geometry. Otherwise choose a more exact object, spatial, language, natural,
  or geometric symbol instead of another generic human reaction or extreme face close-up.

## v8 training (from "We Don't See the Same Color" reference, July 2026)
Cadence:
- 131 wpm, ~16 words/sentence, 28 pauses >0.7s (one every ~6s). Write ellipses and
  hard line breaks at pivots so the VO breathes; let big ideas LAND for 1.5s.
- RHYTHM IS NOT UNIFORM: open with a rapid hook montage (2-4 beats of 1-3s under the
  first sentence), then alternate medium beats (3-5s) with long contemplative holds
  (8-14s) on the heaviest lines. Never a flat 6s-6s-6s pulse.
- To get montage cuts today: split the hook sentence into 2-3 scene entries at natural
  fragment points (alignment handles sub-sentence scenes fine).
Slide selection:
- ACCENT COLOR: pick one color tied to the core concept; the first 2-4 scenes all share
  it as a monochrome motif (e.g., everything red for a video about seeing red).
- WORD-LITERAL PROPS: show the exact noun/verb as an object - lens -> camera lens macro,
  labels -> speech bubble / signs / multilingual words, deeper -> magnifying glass,
  mind -> gears illustration. The prop IS the metaphor.
- MEDIA VARIETY within cohesion: mix stock film with illustrations, 3D renders,
  wireframes, thermal/x-ray imagery - especially for perception-flip beats
  (thermal crowd = literally seeing the same scene in different colors).
- HUMAN BEATS: 3-5 scenes may show people/faces - a thoughtful upward gaze, a person
  pointing AT the camera on a direct-address line. Connection, not anonymity, on those beats.
- CLOSER REFRAME: the final slide should visually reframe the whole premise
  (the thermal crowd after a video about color perception), while the final line
  echoes the title phrase word-for-word.
Content structure (arc template #2, alongside the original hook->diagnosis->turn arc):
1. Sensory thought experiment the viewer performs immediately ("If I open my eyes...")
2. Direct guided-introspection commands: "Think about it." "Now go deeper into your thoughts."
3. Escalation ladder: tiny concrete seed -> "what else could be perceived differently?"
   -> everything (ideas, government, religion, space)
4. Practical micro-instruction: "So pause and notice the labels you use."
5. Title echo as the final sentence.

## DMT genre (v9 training, from "DMT: I Met An Alien" reference)
Trigger: the idea/title involves DMT, ayahuasca, mushrooms, a trip, or a first-person
visionary encounter. Set "genre": "dmt" at the top level of script.json.
The video replicates what the NARRATOR SEES - not moody observation, but vivid vision:
- PALETTE FLIPS: hyper-saturated kaleidoscopes, fractals, neon plasma, cosmic nebulae,
  sacred geometry, bioluminescence - vivid color on deep black. (footage.py scores for
  this automatically when genre is set; the muted lit-but-moody rule is suspended.)
- NARRATOR ANCHOR: open on an ordinary person in an ordinary room (the narrator before
  the dive). Return to that room 1-2 times mid-video and near the end (integration).
  These anchor scenes stay realistic/muted - the contrast IS the story.
- BUILD THE METAPHOR LITERALLY: whatever the narrator says they saw, find footage that
  IS it ("life as translucent slides" -> filmstrip visuals; "scrolling through life" ->
  a person leaving a blurred crowd in a white void). Pin curated clips when needed.
- CADENCE INVERTS: long morphing holds (10-18s) during visionary passages - the footage
  itself moves constantly, so cuts are rare. Quick cuts only at the dive-in moment and
  emphasis beats. Split long visionary sentences less; let scenes run.
- Face projections (patterns cast on the narrator's face) mark the transition between
  the room and the vision.
- Captions/title/music: unchanged from house style.

## Visual symbol grammar (standing rule, July 2026)
- Match the mechanism of the spoken line, not merely its emotional mood. The scene should
  remain conceptually legible even if the caption is hidden.
- A person is one symbol among many, never the universal fallback. When a person appears,
  give the body a job: observer, chooser, explorer, scale reference, collective, creator,
  guardian, performer, or relationship. Avoid generic "thoughtful person looking away"
  footage unless the physical act of looking is the subject.
- Build each normal philosophical video from at least six symbol families: human,
  collective, perception, language, architecture, pathway, identity, time/memory,
  object/tool, nature, world-scale, geometry, transformation, and light/atmosphere.
- Do not use one family for more than three consecutive beats. As a planning target, keep
  human presence at roughly half the runtime or less. People are welcome; repetition is not.
- Alternate four kinds of visual reasoning: literal anchors (printed truth, turning compass),
  structural metaphors (door, wall, path), perspective disruptions (inverted city, recursive
  eye), and human witnesses who provide scale, choice, or consequence.
- Prefer one precise physical symbol over generic mystical filler. A choice can be arrows;
  learned perception can be a gallery of eyes; language failure can be scattered letters;
  a boundary can be nested rings; incomplete knowledge can be a map and compass.
- Repeated primary props are audited across the whole film. If mirrors, doors, phones,
  silhouettes, or any other shorthand dominate, change the symbol family rather than merely
  searching for another version of the same image.
- New scripts use top-level `"visual_policy": "diverse_symbols"`. The planner annotates
  every scene with `semantic_anchor`, `visual_function`, `symbol_family`, `primary_symbol`,
  and—when relevant—`human_role`. It writes `visual_symbol_report.json` before rendering.
- This reference changes visual reasoning, not delivery format: the default output remains
  native 1920x1080 YouTube with the title and picture visible on frame zero.
- June Oxley remains an explicit profile. Keep his literal Southern story world; apply the
  diversity lesson without replacing his concrete character actions with abstract imagery.

## Motion grammar (standing rule, July 2026)
- No more than 35% of the finished runtime may come from still images. Measure seconds,
  not scene count. Static and animated-still durations are added together.
- At least 65% must be genuine temporal footage in which people, objects, light, or the
  recorded environment actually changes—not a camera move across one photograph.
- A crop, pan, push, pull, or Ken Burns move does not change a still's classification.
- An animated still must contain depth-separated or internal subject/environment motion,
  or a visible evolution through controlled keyframes.
- Use 4-8 second moving micro-scenes for complex AI motion; cut before anatomy, identity,
  or background drift becomes visible.
- Preserve quietness through restrained movement rather than absence of movement: breath,
  changing practical light, reflections, curtains, dust, leaves, handwriting, development,
  or literal transformation can carry contemplative scenes.
- Track `static`, `animated_still`, and `video` separately in the render report. Enforce
  the 35% ceiling against `static + animated_still`; animation improves the permitted
  stills but never relabels their source as footage.
- A static/pan/zoom authoring hint is automatically upgraded to the full still-enhancement path.
  This improves the image but does not change its `animated_still` provenance or budget cost.

## June Oxley profile (v15, explicit opt-in)
Trigger only when James explicitly names **June Oxley**. Set the top-level script field:

    "profile": "june_oxley"

Identity and voice:
- June is a retired old white Southern man: slow, raspy, half-distracted, raw, and very funny.
- His dry front-porch humor begins with ordinary aggravations—bills, neighbors, dogs, cousins,
  traffic, church fans—then wanders into consciousness or spiritual absurdity as though that
  turn were perfectly normal.
- The script can pivot atmosphere suddenly (deep truth to absurdity and back). Preserve any
  supplied ElevenLabs chuckle/performance markers verbatim.

Visual grammar learned from the approved reference:
- Ordinary reality is the anchor: hands on an old steering wheel, GPS, cornfield, older people,
  a barking dog, worn mirror, dim-but-readable old house, small church, fireplace, deer,
  traffic, work boots, cigarettes, bills, rural sunrise or sunset.
- Footage is literal to the spoken noun/action. It can be imperfect and slightly homespun;
  authenticity and comic specificity matter more than glossy production value.
- Most scenes are warm and visibly lit by daylight, window light, firelight, or sunset. Do not
  turn June's world into the default pipeline's succession of dark cosmic shots.
- Strange imagery appears only as contrast: an impossible eye, universe in a mirror, cosmic
  interruption over an ordinary field. The everyday world should immediately return.
- Avoid cowboy hats as shorthand, staged Western saloons, caricature costumes, luxury-country
  music-video polish, or making every human shot a generic white stock actor.

Audio grammar:
- Use the profile's restrained 84 BPM front-porch shuffle: woody guitar/banjo twang,
  upright-style root/fifth bass, a soft offbeat brush, and occasional wooden foot-stomp.
- Keep the score VO-adaptive and low in the mix. June's voice and comic timing stay dominant.

Isolation rule:
- `genre` and `profile` are separate. A June DMT story may still use `genre: "dmt"`, but June's
  rural anchors, warm grade, and porch score remain active.
- June approvals and rejections train a separate taste vector. Never apply June's profile or
  learned taste to a video where James did not name him.

## MUSIC CHOICE SYSTEM

Every default render provides one full-length selected score under the narration and picture:
choice 3. That is Deep Current for ordinary philosophical videos, Deep Portal for DMT, and
Creekside Stomp for June Oxley. Keep it VO-adaptive, mastered consistently, and low enough
that language stays dominant. Generate other arrangements only when James explicitly asks
for alternatives through `music_choices`.
