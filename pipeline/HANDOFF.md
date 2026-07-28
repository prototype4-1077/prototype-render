# TikTok Video Pipeline v2 — Instructions for Claude (any model size)

James makes mystical-cinematic philosophical TikToks. This zip is a tested pipeline that turns
an idea into a finished MP4. You only make TWO decisions: write the script, and check the result.
Everything else is one command run in a loop.

## Workflow

1. Unzip to sandbox: `unzip tiktok_pipeline.zip -d pipeline` and `mkdir -p build/<slug>`
   (slug = short-dashed-title, e.g. `dimmer-switch`).

2. WRITE THE SCRIPT (you are the scriptwriter; no API involved). Read style_profile.md first.
   Save as `build/<slug>/script.json` in exactly this shape:

   { "title": "Three Or Four Words",
     "slug": "<slug>",
     "visual_policy": "diverse_symbols",
     "scenes": [
       { "text": "One sentence or beat (max ~25 words).",
         "keywords": ["2-4 load-bearing words from that sentence, highlighted yellow"],
         "semantic_anchor": "the load-bearing idea",
         "visual_function": "literal_anchor|mechanism|choice|boundary|perspective_shift|transformation|recursion|contrast|scale_shift",
         "symbol_family": "human|collective|perception|language|architecture|pathway|identity|time_memory|object_tool|nature|world_scale|geometry|transformation|light_atmosphere",
         "human_role": "only when a person appears",
         "query": "searchable physical action, literal to the line" }
     ] }

   Optional character selector: when—and only when—James explicitly says **June Oxley**,
   add `"profile": "june_oxley"` beside `slug`. Do not use it for ordinary videos.

   Rules (build.py enforces most of them and tells you what to fix):
   - 18-26 scenes, 300-400 words total, ~2:00-2:30 spoken
   - Second-person, poetic-direct, grounded-metaphysical. Hook opener. Quiet realization ending.
   - keywords must be words that literally appear in the scene text
   - Use at least six symbol families, no more than three consecutive scenes from one family,
     and keep human presence around half the runtime or less. A human must have an editorial
     role; never use a generic reaction shot as a universal metaphor.
   - Show James the script text for approval before building, unless he says skip.

3. QUERY BANK — use literal physical anchors and precise metaphors, styled as cinematic and
   lit-but-moody. Surreal imagery is one family, not the default answer to every sentence.
   Legacy mood terms (use only when they explain the line, and mix with other families):
     surreal fog silhouette | nebula space stars | underwater sun rays dark |
     silhouette tunnel light end | fog city aerial dark | smoke swirl black background |
     light rays forest fog | ink drop water black | stars time lapse night sky |
     eclipse moon dark clouds | person walking fog field | abstract particles dark |
     candle flame dark | ocean night moonlight | desert lone figure dusk |
     light through door dark room | clouds time lapse storm dark | mirror reflection surreal |
     glowing orb dark | shadow figure hallway | aurora night sky | deep space travel |
     rain window night bokeh | city lights bokeh night blur
   Query choice matters. Name the object/action that explains the sentence, not simply
   "person thinking" or "mystical silhouette." footage.py can add `symbol_query` when it
   finds weak generic-human filler and writes the audit to visual_symbol_report.json.

   JUNE OXLEY EXCEPTION: use literal, lived-in Southern details before abstract mysticism:
   wooden porch, old white man, old pickup, cornfield, barking dog, small-town traffic,
   kitchen-table bills, country church fan, fireplace, work boots, rural sunset. A few
   cosmic or impossible images should interrupt that ordinary world as deadpan contrast.
   Avoid cowboy costumes and glossy country-video clichés. The profile supplies its own
   brighter warm scoring and fallback bank automatically.

4. BUILD — run this ONE command, then run it again every time it says RUN AGAIN:

       python3 pipeline/build.py build/<slug>

   It loads keys from pipeline/.env itself (no exports needed), downloads fonts on first run,
   validates your script (with fix hints), generates voiceover, downloads footage, renders,
   and finishes by default with exactly one video:
       build/<slug>/final_youtube.mp4   (1920x1080 regular YouTube)
   It uses music choice 3, the current selected score family. Portrait, short, and
   alternate-music videos are opt-in only. Set `render_outputs` to any combination
   of `youtube`, `portrait`, and `short`; set `music_choice` and
   `music_choices` only when James explicitly requests a different or additional mix.
   Rules of thumb:
   - Every step is resumable. Rerunning never breaks anything.
   - If a bash call times out, just run the same command again.
   - On `ERROR: ... | FIX: ...` do exactly what FIX says, then rerun.

5. VERIFY (only judgment step besides the script): extract 3 frames and look at them:
       ffmpeg -y -ss 3 -i build/<slug>/final_youtube.mp4 -frames:v 1 f1.png
   Confirm the native 16:9 canvas fills the frame without stretching, yellow keyword
   captions are safe, and the rounded scene-0 title is fully visible. Check duration
   (~2:00-2:40) plus visual_symbol_report.json and motion_report.json.
   If one scene's footage looks wrong: delete its clip_XX.mp4 AND seg_XX.mp4, improve that
   scene's "query" in script.json, remove its "pexels_id", and rerun build.py.

6. DELIVER: present final_youtube.mp4 and the required scene survey. Only include
   additional canvases or soundtrack files when James explicitly requested them. Done.

## Required scene review after every render
A successful build automatically creates `scene-review.html` and
`scene-review.json`. The HTML file is a standalone review form with one numbered block
per scene: preview frame, narration, visual description, selection rationale,
Approve/Needs revision controls, and a comments area. It autosaves in the browser and
exports `<slug>-scene-feedback.json`.

Return that exported JSON to the pipeline with:

    python3 pipeline/learn.py survey build/<slug> <slug>-scene-feedback.json

Approved scenes positively train clip/query taste. Scenes marked Needs revision require a
comment; their source clips are banned and cleared so only those scenes rerender.
The overall approval is recorded only when James selects it. Never infer approval.

## Look spec (what "correct" looks like)
- Every default build creates one 30fps native 1920x1080 regular-YouTube canvas.
  It is recomposed directly from source footage and is never a stretched portrait render.
- YouTube captions remain inside the landscape safe area with 2-4 keywords per
  sentence in pale yellow (#e6e87e).
- Title: Baloo2 ExtraBold ALL-CAPS white with shadow, centered over the footage band,
  scene 0. Long titles automatically wrap and shrink to remain inside the safe area.
  Use at most two words per title line; allow three only when the line includes a short
  connector/function word such as `I`, `a`, `the`, `on`, `of`, or `to`.
- Audio: ElevenLabs VO (voice id in .env; James's current pick is Liam) over a low ambient bed.

## Config
- .env: ELEVENLABS_API_KEY, PEXELS_API_KEY, ELEVENLABS_VOICE_ID (Liam TX3LPaxmHKxFdv7VOQHJ;
  Daniel onwK4e9ZLuTAKqWW03F9 is the old calm-deep option). Ask James once per video if unsure.
- Optional outputs: set "render_outputs": ["youtube", "portrait", "short"] only for
  canvases James explicitly requests.
- Optional score alternatives: keep "music_choice": 3 as the primary and add
  "music_choices": [3, 1, 2] only when James explicitly requests choices.
- Custom music: put a file in the build dir and set "music": "<filename>" in script.json.
  It becomes the one selected soundtrack unless alternatives are explicitly declared.

## Files
build.py   — THE orchestrator; the only command you need after writing the script
style_profile.md — James's writing voice + reference fragments (read before scripting)
tts.py, footage.py, prep.py, captions.py, music.py, assemble.py — internals (don't edit)
.env       — API keys

## v3: the pipeline is ALIVE (it learns between videos)
- memory.json (in this zip) persists across videos. NEVER delete it; always include it when re-zipping.
- Before writing any script: `python3 pipeline/learn.py show` — read James's notes and what worked.
- footage.py automatically: never reuses a clip from past videos, never picks banned clips,
  favors bank queries with the best track record. You don't manage this; it just happens.
- After James APPROVES a final video: `python3 pipeline/learn.py record build/<slug>`
- If James dislikes one scene's footage: `python3 pipeline/learn.py swap build/<slug> <scene_i>`
  (bans that clip forever + penalizes the query), optionally improve that scene's "query",
  then rerun build.py. Repeat until he's happy, THEN record.
- If James gives any feedback in chat worth remembering: `python3 pipeline/learn.py note "..."`
- When you deliver the final video, ALSO re-zip the pipeline folder (with the updated memory.json)
  and present it to James so the memory survives to his next session. This is what makes the
  videos living: each session inherits everything every past session learned.

## v3: James can supply his own voiceover
Drop his mp3 in the build dir as vo.mp3 BEFORE the first build.py run (and add "user_vo": true
in script.json). build.py then skips TTS, force-aligns his script text to his audio for exact
scene timing (align.py), and relaxes the word/scene-count limits (his script is authoritative —
split it into scenes VERBATIM, never rewrite his words).

## v3: the music listens
music.py reads the voiceover's energy: it recedes under speech, swells in the pauses,
sprinkles soft chimes at long-pause onsets, and builds ~30% toward the closing line.
Nothing to configure. For custom music set "music" in script.json as before.

Every default render produces one full-video soundtrack: choice 3. Its label is Deep
Current for ordinary philosophy videos, Deep Portal for DMT, and Creekside Stomp for
June Oxley. Additional choices are synthesized only when `music_choices` explicitly
requests them.

## v5 upgrades (all automatic; nothing new to operate)
- WORD-SYNCED CAPTIONS: if `faster-whisper` is installed (pip install faster-whisper),
  build.py transcribes the VO locally and yellow keywords ignite at the exact moment they
  are spoken. Without it, captions fall back to static yellow. Env WHISPER_MODEL can point
  to a local model dir (default "base", auto-downloads).
- SEMANTIC FOOTAGE MATCHING: with open_clip_torch+torch installed AND env SEMANTIC_CLIP=1
  (auto-on in GitHub Actions), every candidate clip is also scored by CLIP for how well it
  matches the scene's query meaning, blended with the mood score. Leave off in 45s-limited
  sandboxes (model load is ~30s). Env CLIP_CACHE = model dir (default /tmp/clipcache).
- LOUDNESS MASTER: the final mix is automatically mastered to ~-14 LUFS / -1 dBTP
  (TikTok reference). Nothing to configure.
- GITHUB RENDER FARM: if this pipeline lives in a GitHub repo (see github_repo/README.md),
  trigger the "Render video" workflow with a slug instead of running build.py locally:
  no time limits, CLIP on, memory.json auto-committed back. Prefer it for full renders
  when available; use local build.py for quick tests and single-scene fixes.

## v7 upgrades
- CINEMATIC COHESION (automatic): unified color grade + film grain + vignette, camera
  motion alternates per scene (push-in / pull-out / drift), dip-to-black scene cuts,
  title fades in/out. Nothing to configure.
- 60s SHORT CUT (opt-in): add `short` to render_outputs. build.py then writes
  final_short.mp4 from the strongest beats using the selected score family.
  Manual: python3 pipeline/shortcut.py build/<slug> [target_secs]
- MYTHOLOGY: memory.json now holds "motifs" (one signature line per video). When
  scriptwriting, echo exactly ONE earlier motif mid-video as a natural callback phrase.
  After each approved video: python3 pipeline/learn.py motif <slug> "<name>" "<line>"
- RETENTION LEARNING: when James shares TikTok retention drop-off timestamps:
  python3 pipeline/learn.py retention build/<slug> "43,87,110"
  It maps them to scenes and records the lesson; future scripts obey.
- ISSUE STUDIO (GitHub): open an issue labeled "video" whose title/body is the idea.
  CI writes the script (free keyless LLM; ANTHROPIC_API_KEY secret optional for higher quality), renders, comments
  the artifact link on the issue. Closing the issue = approval.

## v10: HERO SHOTS (free AI imagery, no API keys)
For 2-4 metaphor beats per video that stock can never match, add to the scene:
    "hero": true, "image_prompt": "exactly what the shot shows (no style words needed)"
build.py generates the image (pollinations.ai, keyless), estimates depth locally
(MiDaS ONNX), completes newly exposed background edges, and renders a layered
cinemagraph with restrained internal movement as that scene's clip.
Genre styling is automatic (moody film still vs vivid visionary for dmt).
Use for: impossible metaphors (wall of doors, translucent slides), the title/thumbnail
scene, and the closer reframe. Stock remains the default for ordinary beats.
If generation fails the build falls back to stock via the scene's "query".

## v11: CINEMATIC SCORE + SOUND DESIGN (all synthesized, free, automatic)
music.py v3 composes a real score per video: minor chord pads with synthetic reverb,
deep drone, airy swells, heartbeat pulse (philosophy) or shimmering plucks (dmt genre),
in true stereo - still VO-adaptive (recedes under speech, blooms in pauses, builds to
the ending). sfx.py then bakes sound design into the bed from scene timings: a sub-drop
under the title and the closing line, whooshes into cuts after long holds, and a riser
into the final scene. Nothing to configure; genre is read from script.json.

## v12: MULTI-SOURCE FOOTAGE + ALTERNATES (all keyless)
- Footage now draws from Pexels + NASA (space queries -> real telescope/mission footage),
  Internet Archive Prelinger (vintage film, auto-added for dmt genre), Wikimedia Commons
  (fallback), and Pixabay if a free PIXABAY_API_KEY secret is ever added. Same scorer
  ranks everything; ids are namespaced (nasa:..., ia:..., wm:...).
- Every scene stores its top-3 runner-up candidates (alts.json + thumbnails). The build
  produces alts_sheet.jpg (chosen frame + alternates per scene) in the run artifacts.
- Swapping is now surgical: python3 pipeline/learn.py pin build/<slug> <scene_i> <id>
  (any id from alts.json or manual curation), then rerun/re-dispatch. Pins re-fetch
  deterministically across all sources.

## v13: PERMANENT ARCHIVE + SPEED + BATCH
- Every successful render now publishes a GitHub RELEASE (tag video-<slug>) with the
  final MP4s + review sheet attached - permanent, unlike artifacts which expire in 90 days.
  Download from the repo's Releases page.
- Whisper/CLIP/depth models are cached between CI runs (faster starts).
- BATCH: Actions -> "Render batch" -> comma-separated slugs renders them in parallel.
- Issue studio is now FREE: idea_writer.py falls back to pollinations.ai text API when
  no ANTHROPIC_API_KEY secret exists.

## v14: LEARNED TASTE VECTOR
Every render stores the chosen clip's CLIP embedding (emb_XX.npy, committed back by CI).
learn.py record -> those embeddings become "approved"; learn.py swap -> "rejected".
Once >=8 approved exist (pipeline/taste.npz) the footage ranker blends a learned taste
term (0.38 mood / 0.47 semantic / 0.15 taste) - the system scores candidates by
similarity to James's actual approval history, learning aesthetics no rule captures.
Nothing to configure. ALWAYS commit pipeline/taste.npz together with memory.json
after record/swap. No backfill needed; it learns forward from every video.

## v15: JUNE OXLEY CHARACTER PROFILE (explicit opt-in)
Set `"profile": "june_oxley"` only when James names June Oxley. The profile:
- expands literal footage searches toward candid Southern rural/small-town life;
- favors warm, visibly lit frames and rejects near-black footage;
- turns hero images into grounded Southern folk-surrealism instead of generic fantasy;
- replaces the ambient cinematic bed with an 84 BPM front-porch shuffle made from
  synthesized guitar/banjo twang, upright-style bass, soft brush, and wooden foot-stomps;
- stores approved/rejected CLIP taste under June-specific arrays, isolated from house taste.
All captions, scene-0 title behavior, portrait 9:16 letterboxing, native 16:9 YouTube
composition, VO ducking, and the default style for every other video remain unchanged. `character: "June Oxley"` is accepted as an alias,
but `profile: "june_oxley"` is the canonical field.

## v17: MOTION COMPILER + 35% STILL-SOURCE CAP
Motion is measured by duration, never inferred from an MP4 extension. A pan, crop, or
zoom applied to one photograph remains a `static` shot. Depth motion and evolving
keyframes improve an image but remain still-derived. Every build writes
`motion_report.json` and fails when `static` plus `animated_still` duration exceeds
the top-level `max_still_source_ratio` (default `0.50`). At least 50% must be genuine
moving footage. Source classes are:

- `static`: still, pan, zoom, or Ken Burns only;
- `animated_still`: depth-separated layers, internal/cinemagraph motion, evolving
  keyframes, or portrait motion;
- `video`: recorded/stock footage or true image-to-video generation.

To animate a supplied/generated image without a GPU:

    {"source_image": "still_04.png", "motion_mode": "depth"}

Optional `motion_recipe` values are `human`, `organic`, `paper`, `screen`,
`reflection`, `light`, and `atmosphere`; otherwise the literal scene text selects one.
The compiler uses CPU depth estimation, an inpainted background plate, separate depth
layers, practical-light motion, and restrained recipe-specific movement.

For visible transformations, provide two or more staged images:

    {"keyframes": ["seed_0.png", "seed_1.png", "seed_2.png"],
     "motion_mode": "keyframes"}

If `RIFE_BIN` points to a `rife-ncnn-vulkan` executable it is used in CPU mode;
otherwise OpenCV optical flow provides a deterministic fallback. Stock remains the
right source for ordinary physical actions and must occupy at least 65% of runtime.
The motion compiler improves the permitted 35% of still-derived quiet tableaux and
impossible metaphors; it never converts them into the `video` class.

Downloaded footage is checked for independent temporal change after median/global
camera flow is removed. A `video` scene must carry `motion_verified: true` and its
evidence in `motion_report.json`; otherwise the build fails. Keyless Coverr stock is
the primary local fallback when Pexels credentials are absent, Mixkit is secondary,
and `CREDITS.txt` is emitted for source/license attribution. The automatic short cut
independently enforces the same 35% still-source ceiling.

## v18: VISUAL SYMBOL PLANNER + DIVERSITY AUDIT
Every scene now has an explicit visual job. `visual_symbols.py` classifies or preserves its
`symbol_family`, identifies the `semantic_anchor` and `visual_function`, records a
`primary_symbol`, and assigns `human_role` whenever a person is part of the image.

For a missing query or a vague reaction shot such as "thoughtful person looking away," the
planner may add `symbol_query`. This does not rewrite narration or erase the original query;
it gives footage search a concrete physical metaphor derived from the spoken line. Concrete
human actions—entering a room, drawing an arrow, returning an object to a shelf—remain intact.
June Oxley queries are never abstracted away from his literal character action.

New scripts set `"visual_policy": "diverse_symbols"`. Before downloads begin, the build
requires a varied symbol vocabulary, limits long same-family runs, limits generic human
filler, and targets human presence at roughly half the runtime or less. Older scripts without
that flag receive the same annotations and an advisory report without being blocked.

Every build writes `visual_symbol_report.json` with per-scene reasoning, effective search
queries, human roles, family counts, repetition warnings, and a transparent diversity score.
Manual commands:

    python3 pipeline/visual_symbols.py plan build/<slug>
    python3 pipeline/visual_symbols.py validate build/<slug>
    python3 pipeline/visual_symbols.py report build/<slug>

## v19: STOCK-FRAME-CONDITIONED STILLS + FULL ENHANCEMENT
The orchestrator now downloads and verifies genuine stock scenes before touching a still.
For each hero, supplied still, or keyframe sequence, `still_reference.py` ranks the already
selected stock scenes by literal token overlap, symbol family, primary prop, visual function,
and timeline distance. It saves the public frame from the closest related stock clip as
`stock_reference_NN.jpg`.

Generated hero images use that exact public frame URL as Pollinations Kontext image-to-image
input. The prompt changes the subject/action while preserving the film's camera language,
lens perspective, exposure, practical light, palette, depth, and production realism. A local
harmonization pass then matches restrained LAB color/exposure and restores natural detail.
Supplied images are never overwritten; enhanced copies are written as
`enhanced_still_NN*.jpg`.

Every still then receives depth-separated foreground/mid/background movement, inpainted
occlusion completion, recipe-specific internal motion, practical-light movement, the shared
final grade, and film grain. Static, pan, zoom, and Ken Burns modes are automatically upgraded;
they are not accepted as finished still treatments. Keyframe transformations retain their
controlled optical-flow/RIFE evolution after reference matching.

If a generated hero cannot obtain or use a public stock frame, `build.py` falls back to genuine
stock footage for that beat rather than emitting an isolated unreferenced still. Every build
writes `still_reference_report.json`; delivery fails if an active still lacks a current closest
stock reference or any required enhancement step. These images remain `animated_still` and
continue to count in full toward the 35% still-source ceiling.

## v20: THREE-WAY MUSIC CHOICE
`prep.py` now creates at least three distinct VO-adaptive score beds for every video.
`build.py` mixes and masters each one against the same narration and picture, producing
`final_music_01.mp4`, `final_music_02.mp4`, and `final_music_03.mp4`. The selected labels,
source files, and output names are written to `music_variants.json`; `final.mp4` remains a
copy of choice 1 so older automation keeps working. A custom score becomes choice 1 and the
pipeline generates enough alternatives to keep the total at three. GitHub artifacts and
permanent Releases include every choice.

## v21: DUAL SOCIAL + REGULAR-YOUTUBE EXPORT
Every completed build now renders the same timed edit twice: the established
1080x1920 portrait version and a separately composed 1920x1080 landscape version.
Landscape files use `final_youtube.mp4` and `final_youtube_music_NN.mp4`; portrait
names remain unchanged for backward compatibility. `music_variants.json` records
both names, and GitHub artifacts and permanent Releases publish both sets.

## v22: DEEP CURRENT DEFAULT DELIVERY
Every render still generates and archives all three complete music choices. The
`delivery` object in `music_variants.json` selects Deep Current (choice 3 in the
standard profile) and names its portrait and 1920x1080 YouTube files. Default delivery
shows only those two download links. The other choices remain available on request but
their links are not surfaced automatically.


## July 2026 upgrades (quality, learning, efficiency)

- Encode policy lives in `video_format.py` (`ENCODE_QUALITY` slow/CRF18 +
  BT.709 `COLOR_TAGS`, 256k audio). Footage renditions never upscale: the
  picker targets the 1920px master canvas (`footage.pick_file`).
- Audience loop: after uploading, dispatch the "Record published video"
  workflow (or `learn.py published <slug> <video_id>`); the nightly
  analytics workflow converts YouTube retention curves into per-scene
  query/taste learning. Setup: `pipeline/ANALYTICS.md`. Evidence digest:
  `pipeline/WHATS_WORKING.md` (regenerate with `learn.py digest`).
- Taste scoring upgrades to a logistic head automatically once it has
  >=30 approved and >=8 rejected embeddings; query weights decay 2% per
  recorded video so recent wins outvote old habits.
- Hook A/B: declare visual-only `hook_variants` in script.json and run
  `python3 pipeline/hook_variants.py build/<slug>` after a normal build;
  only overridden scenes re-render (`final*_hook<label>.mp4`).
- Voice: opt into Eleven v3 per script with `"elevenlabs_model": "eleven_v3"`
  (inline audio tags like [whispers] give per-beat emotional direction).
- Renders: Governor default budget is 45 min (`long_render: true` restores
  78); `use_container: true` runs in the prebuilt ghcr image once the
  package is public; per-slug footage caching speeds retries.
- `coherence_report.json` (informational) flags visually jarring cuts.


## Fallback visuals rule (James)

When genuine stock footage cannot be found for a scene, the pipeline does NOT
use a flat text/label graphic. It auto-generates an appealing SPECIAL-EFFECTS
STILL IMAGE representing the line (glowing particles, volumetric light, depth,
cinematic grade) via hero.py, then animates it with a depth push. See
storyline_footage._render_storyboard and EFFECTS_STILL_STYLE. Any scene can force
this look by setting "hero": true with an "image_prompt".
