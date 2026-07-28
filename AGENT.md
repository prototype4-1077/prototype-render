# AGENT.md — Instructions for any AI operating this repo

> CANONICAL REPO: This project lives at prototype-video/Prototype-Video. James makes ALL videos here. Do every video request in this repo; never use jameswatson1077/tiktok-videos or 1974jwatson/TikTok-Video-Pipeline (both are retired earlier homes of this pipeline).


You are making a mystical-philosophical TikTok video for James using this repo's
cloud render farm. You need NO video tools — GitHub Actions renders everything.
You only need: (1) the connected GitHub app, (2) this file.

REPO: prototype-video/Prototype-Video (private)
ACCESS: Use the workspace's connected GitHub app. This connection is persistent across
ChatGPT/Codex instances. Never ask James to paste a personal access token and never put a
credential in a file, command, commit, or response. If the GitHub app is unavailable, report
that connection as the blocker instead of requesting a secret.
API BASE: https://api.github.com/repos/prototype-video/Prototype-Video
MEDIA POLICY: never commit video/audio/base64 media except the documented
build/<slug>/vo.mp3 connector path; finished media belongs in Releases/artifacts.

AUDIENCE LOOP: after uploading a build to YouTube run
`python3 pipeline/learn.py published <slug> <video_id>` and commit
pipeline/published_videos.json; the nightly analytics workflow feeds real
retention back into memory.json/taste.npz and refreshes WHATS_WORKING.md
(setup: pipeline/ANALYTICS.md).
VOICE: opt into Eleven v3 per script with "elevenlabs_model": "eleven_v3" and
inline audio tags for emotion. HOOK A/B: visual-only "hook_variants" in
script.json + pipeline/hook_variants.py (see pipeline/HANDOFF.md).
## Step 0 — Read context (GET file contents via API or git clone)
- pipeline/HANDOFF.md      — full pipeline docs
- pipeline/style_profile.md — James's writing voice + visual spec
- pipeline/memory.json      — READ "notes" (his standing feedback) and respect it.
  Current standing rules: slides must be LIT-but-moody (window light, god rays,
  lamplight, golden hour; only a few near-dark slides), footage must match the
  spoken words (especially endings). By default, every build creates exactly one
  native 1920x1080 16:9 regular-YouTube video named final_youtube.mp4. It uses the
  current selected score family (choice 3: Deep Current normally, Deep Portal for
  DMT, Creekside Stomp for June). Do not generate portrait, short, or alternate-music
  MP4s unless James explicitly requests them. Opt in per script with render_outputs
  (youtube, portrait, short), music_choice, and music_choices. Titles and captions
  must remain safely composed for every explicitly requested canvas.
  No more than 35% of finished runtime may come from still images. Animated stills,
  depth moves, keyframes, and pan/zoom all count toward that 35%; at least 65% must
  be genuine footage where people or objects actually move. Check
  motion_report.json before delivery.
  Acquire genuine stock scenes before creating any still. Every still must begin
  from the saved public frame of the closest related selected stock scene, receive
  the complete reference/exposure/detail/depth/background/internal-motion/light/
  grade/grain path, and pass still_reference_report.json. Never use raw stills or
  pan/zoom-only slides; if reference-conditioned generation fails, use stock video.
  Match the MECHANISM of each spoken line, not merely its mood. A person is one
  symbol among many and must have a role (observer, chooser, explorer, scale,
  collective, creator, guardian, performer, relationship). New normal videos use
  at least six symbol families, no more than three consecutive beats from one
  family, and roughly half or less human presence. Avoid generic thoughtful-person
  footage. Check visual_symbol_report.json before delivery.
  Every render creates one selected background-music mix by default. The canonical
  deliverable is final_youtube.mp4 and music_variants.json records the selected score.
  Additional score choices or canvases are opt-in only when James asks for them.

## Step 1 — Write the script file
Create build/<slug>/script.json  (slug = short-dashed-title):
{ "title": "Three Or Four Words", "slug": "<slug>",
  "visual_policy": "diverse_symbols",
  "scenes": [ { "text": "One sentence/beat (max ~25 words).",
                "keywords": ["2-4 words that appear IN that text"],
                "semantic_anchor": "load-bearing idea",
                "visual_function": "what the image explains",
                "symbol_family": "one family from visual_symbols.py",
                "human_role": "only if a person appears",
                "query": "physical searchable action: lit-but-moody, literal to the line" } ] }
Rules: 18-26 scenes and 300-400 words if YOU write the script (second person,
poetic-direct, quiet powerful ending — see style_profile.md).
If James supplies script text: split it into scenes VERBATIM (never rewrite), any length.
If James supplies a voiceover mp3: also commit it as build/<slug>/vo.mp3 and put
"user_vo": true at the top level. (vo.mp3 is gitignored — force-add it: git add -f,
or use the contents API which ignores .gitignore.)
If James explicitly says **June Oxley**, add top-level `"profile": "june_oxley"`.
Never infer this profile for another video. It automatically changes only that video's
footage search/ranking, warm rural grade, hero-shot styling, music, sound design, and
separate taste learning. See the June Oxley section in `pipeline/style_profile.md`.
Show James the script for approval before rendering unless he says skip.

## Step 2 — Commit
Via git push, or via API (works without git; handles base64 for the mp3):
PUT /contents/build/<slug>/script.json   {"message":"...","content":"<base64>"}
PUT /contents/build/<slug>/vo.mp3        {"message":"...","content":"<base64 of mp3>"}

## Step 3 — Render
POST /actions/workflows/render.yml/dispatches   {"ref":"main","inputs":{"slug":"<slug>"}}
Expect HTTP 204. Takes ~10-15 min.

## Step 4 — Poll + fetch result
GET /actions/runs?per_page=1        -> id, status ("completed"), conclusion ("success")
GET /actions/runs/<id>/artifacts    -> archive_download_url
GET that url (same auth, follow redirects) -> zip containing final_youtube.mp4,
music_variants.json, reports, and the required scene survey. Deliver the one YouTube
video by default. Additional canvases or music choices appear only when explicitly
requested in the script.
If conclusion is "failure": GET /actions/runs/<id>/logs, find the "ERROR: ... | FIX: ..."
line, apply the FIX (usually edit script.json), push, re-dispatch.

## Step 5 — The learning loop (IMPORTANT — this keeps the videos improving)
- James approves → in a checkout run: python3 pipeline/learn.py record build/<slug>
  then commit+push pipeline/memory.json and pipeline/taste.npz. Profiled taste is kept
  separate automatically. (No shell? Skip; tell James it's unrecorded.)
- James dislikes scene i's footage → python3 pipeline/learn.py swap build/<slug> <i>,
  improve that scene's "query", commit, re-dispatch.
- James gives style feedback → python3 pipeline/learn.py note "<his feedback>",
  commit memory.json. Never delete memory.json.

## Scene review survey (required after every finished render)
Every successful video must ship with `scene-review.html` and `scene-review.json`.
The standalone HTML survey numbers every scene, shows its preview frame, narration,
visual description, and rationale, and collects an Approve/Needs revision decision plus
scene-specific comments. Do not deliver a finished video without its survey.

James exports `<slug>-scene-feedback.json` from the survey and returns it for learning.
Apply it with `python3 pipeline/learn.py survey build/<slug> <feedback.json>`.
This command positively weights approved clips, bans and clears rejected clips, records
comments as durable scene feedback, updates the taste vector, and prepares only rejected
scenes for rerendering. Never mark scenes or the overall video approved on James's behalf.

## Judgment checklist before delivering
Duration ≈ VO length; default final_youtube.mp4 is 1920x1080 with captions and the
bold rounded scene-0 title safely fitted; title lines use at most two words, or three
only when one is a short connector/function word such as `I`, `a`, `the`, `on`, `of`, or `to`;
majority of slides visibly lit; every clip
matches its spoken line; at least six visual symbol families; no repeated generic-human
run; still-derived duration <=35% and genuine moving footage >=65%; every still passes
still_reference_report.json and visibly belongs beside its stock reference. Confirm
exactly the requested MP4 outputs exist and the selected score matches
music_variants.json before delivery.

## v7 additions
- By default, generate and deliver only final_youtube.mp4 with the selected third score
  family. Portrait, short, and alternate-music MP4s are created only after an explicit
  request and must be listed in render_outputs/music_choices.
- Scripts must echo ONE motif from memory.json "motifs" as a brief mid-video callback.
- Retention feedback: python3 pipeline/learn.py retention build/<slug> "<t1,t2>" then push memory.
- RETIRED: issue-based "zero-effort mode". Opening a GitHub issue labeled "video" does
  NOT build or render anything on this repository. (idea.yml only reacts to issues titled
  "Render existing:", and ANTHROPIC_API_KEY is not configured here.) Issues #1-#3 predate
  this change and were never processed - treat them as idea notes, not queued work.
- CURRENT submission path: commit build/<slug>/submission.json. A workflow expands it into
  the full package, preserves narration exactly, and triggers the render on its own.
  The authoritative spec is THINK_TANK_CONTRACT.md at the repository root.

## Parallel operators
Multiple AIs may work simultaneously, each on its OWN slug. Rules:
- Never touch another slug's build dir. Pick a fresh slug; check build/ first.
- If your git push is rejected: git pull --rebase origin main, then push again (retry a few times).
- CI enforces one run per slug at a time; different slugs render in parallel.
- Record/note/swap (learn.py) immediately before pushing, then push promptly - memory
  is shared, last-writer-wins on notes is fine, but always pull-rebase first.
- Tricky prop shots can be PINNED: set the scene's "pexels_id" to a curated clip id; the build fetches that exact clip.
- DMT/visionary scripts: set "genre": "dmt" in script.json (see style_profile.md DMT
  section). Footage scoring flips to vivid/saturated automatically.
- HERO SHOTS: scenes may set "hero": true + "image_prompt" - CI generates free AI
  imagery (pollinations.ai) with a 2.5D parallax move instead of stock. Use for
  impossible metaphors, the scene-0 thumbnail, and the closing reframe (2-4 per video).
- ALTERNATES: after a render, build/<slug>/alts.json lists runner-up clips per scene and
  the run artifact alts_sheet.jpg shows them. Swap = learn.py pin build/<slug> <i> <id>,
  then re-dispatch. Prefer pinning an alternate over re-rolling queries.
