"""Generate a standalone per-scene review survey for every finished video."""

import argparse
import base64
import copy
import hashlib
import html
import json
import os
import subprocess
from datetime import datetime, timezone


SCHEMA_VERSION = 1
FUNCTION_LABELS = {
    "literal_anchor": "show the spoken action directly",
    "mechanism": "make the cause-and-effect mechanism visible",
    "choice": "make the choice legible without captions",
    "boundary": "show the line or limit being described",
    "perspective_shift": "reframe the idea from a new point of view",
    "transformation": "show a clear before-and-after change",
    "recursion": "echo the idea through repetition",
    "contrast": "make the contrast in the narration visible",
    "scale_shift": "change scale to clarify the idea",
    "identity": "make the identity beat visually specific",
}


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _timecode(seconds):
    seconds = max(0, int(float(seconds or 0)))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _video_path(build_dir, explicit=None):
    if explicit:
        return explicit
    manifest_path = os.path.join(build_dir, "music_variants.json")
    if os.path.exists(manifest_path):
        try:
            manifest = json.load(open(manifest_path, encoding="utf-8"))
            delivery = manifest.get("delivery") or {}
            for key in ("youtube_video", "portrait_video"):
                candidate = delivery.get(key)
                if candidate and os.path.exists(os.path.join(build_dir, candidate)):
                    return os.path.join(build_dir, candidate)
        except (OSError, ValueError, TypeError):
            pass
    for name in ("final_youtube.mp4", "final.mp4"):
        candidate = os.path.join(build_dir, name)
        if os.path.exists(candidate):
            return candidate
    return None


def _preview_data_uri(video, scene):
    if not video or not os.path.exists(video):
        return None
    start = float(scene.get("start") or 0)
    duration = max(0.2, float(scene.get("duration") or 1))
    midpoint = start + min(duration * 0.5, max(0.1, duration - 0.1))
    cmd = [
        "ffmpeg", "-v", "error", "-ss", f"{midpoint:.3f}", "-i", video,
        "-frames:v", "1", "-vf", "scale=540:-2", "-q:v", "6",
        "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode or not result.stdout:
        return None
    encoded = base64.b64encode(result.stdout).decode("ascii")
    return "data:image/jpeg;base64," + encoded


def _why_chosen(scene):
    anchor = (scene.get("semantic_anchor") or scene.get("text") or
              "the central spoken idea").strip().rstrip(".")
    function = scene.get("visual_function") or "literal_anchor"
    purpose = FUNCTION_LABELS.get(function, function.replace("_", " "))
    family = (scene.get("symbol_family") or "visual").replace("_", " ")
    source = scene.get("motion_mode") or scene.get("motion_source") or "moving footage"
    return (
        f"Chosen to {purpose}: {anchor}. The {family} symbol family keeps the "
        f"visual language varied, and {source} was used to preserve visible motion."
    )


def _scene_payload(scene, index, preview=None):
    source_id = scene.get("pexels_id") or scene.get("stock_id")
    description = (scene.get("query") or scene.get("image_prompt") or
                   scene.get("primary_symbol") or "Visual selected for this narration beat.")
    return {
        "scene_index": index,
        "scene_number": index + 1,
        "start_seconds": round(float(scene.get("start") or 0), 3),
        "duration_seconds": round(float(scene.get("duration") or 0), 3),
        "timecode": _timecode(scene.get("start")),
        "narration": scene.get("text") or "",
        "visual_description": description,
        "why_chosen": _why_chosen(scene),
        "visual_function": scene.get("visual_function"),
        "symbol_family": scene.get("symbol_family"),
        "motion_mode": scene.get("motion_mode") or scene.get("motion_source"),
        "source_id": source_id,
        "source_url": scene.get("source_url"),
        "decision": "unreviewed",
        "comments": "",
        "preview": preview,
    }


def _fingerprint(script):
    stable = {
        "slug": script.get("slug"),
        "scenes": [
            {
                "text": scene.get("text"),
                "query": scene.get("query"),
                "source_id": scene.get("pexels_id") or scene.get("stock_id"),
            }
            for scene in script.get("scenes", [])
        ],
    }
    raw = json.dumps(stable, sort_keys=True, ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ - Scene Review</title>
<style>
:root {
  color-scheme: light;
  --paper: #ffffff;
  --page: #f2f4f5;
  --ink: #17191a;
  --muted: #62696d;
  --line: #d7dcdf;
  --approve: #18764f;
  --approve-bg: #e8f5ee;
  --revise: #b13b32;
  --revise-bg: #fbeceb;
  --accent: #d3b514;
  --focus: #256f99;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--page);
  color: var(--ink);
  font: 15px/1.45 Arial, Helvetica, sans-serif;
}
button, input, textarea { font: inherit; }
.topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  background: var(--paper);
  border-bottom: 1px solid var(--line);
}
.topbar-inner, main {
  width: min(1180px, calc(100% - 32px));
  margin: 0 auto;
}
.topbar-inner { padding: 16px 0 12px; }
.heading-row, .toolbar, .status-row, .scene-head, .decision-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.heading-row { justify-content: space-between; }
h1 { margin: 0; font-size: 22px; letter-spacing: 0; }
.subtitle { margin: 3px 0 0; color: var(--muted); }
.toolbar { flex-wrap: wrap; margin-top: 12px; }
button, .file-button {
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--paper);
  color: var(--ink);
  padding: 8px 11px;
  cursor: pointer;
}
button:hover, .file-button:hover { border-color: #92999d; }
button.primary { background: var(--ink); color: #fff; border-color: var(--ink); }
button.approve-all { color: var(--approve); border-color: #8cc6aa; }
.filter.active { border-color: var(--focus); color: var(--focus); }
.progress-track {
  height: 5px;
  background: #e3e7e9;
  margin-top: 12px;
  overflow: hidden;
}
.progress-bar { height: 100%; width: 0; background: var(--approve); }
.status-row { justify-content: space-between; margin-top: 7px; color: var(--muted); font-size: 13px; }
main { padding: 22px 0 60px; }
.scene-list { display: grid; gap: 14px; }
.scene {
  display: grid;
  grid-template-columns: 250px minmax(0, 1fr);
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
}
.scene[data-decision="approved"] { border-left: 5px solid var(--approve); }
.scene[data-decision="revise"] { border-left: 5px solid var(--revise); }
.preview {
  min-height: 360px;
  background: #090909;
  display: grid;
  place-items: center;
  color: #a8adb0;
}
.preview img { display: block; width: 100%; height: 100%; object-fit: contain; }
.scene-body { padding: 18px; min-width: 0; }
.scene-head { justify-content: space-between; border-bottom: 1px solid var(--line); padding-bottom: 10px; }
.scene-number { font-weight: 700; font-size: 18px; }
.timecode { color: var(--muted); font-variant-numeric: tabular-nums; }
.narration { margin: 14px 0; font-size: 17px; }
.meta-block { margin: 12px 0; }
.meta-label {
  display: block;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  margin-bottom: 3px;
}
.meta-text { margin: 0; overflow-wrap: anywhere; }
details { border-top: 1px solid var(--line); padding-top: 10px; margin-top: 12px; }
summary { cursor: pointer; color: var(--muted); }
.render-details { margin-top: 9px; color: var(--muted); font-size: 13px; }
.review-box { border-top: 1px solid var(--line); margin-top: 14px; padding-top: 14px; }
.decision-row { flex-wrap: wrap; }
.decision {
  position: relative;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 8px 12px;
  cursor: pointer;
}
.decision input { margin: 0 7px 0 0; }
.decision.approved:has(input:checked) {
  color: var(--approve);
  border-color: var(--approve);
  background: var(--approve-bg);
}
.decision.revise:has(input:checked) {
  color: var(--revise);
  border-color: var(--revise);
  background: var(--revise-bg);
}
textarea {
  width: 100%;
  min-height: 88px;
  resize: vertical;
  margin-top: 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 10px;
  color: var(--ink);
  background: #fff;
}
textarea:focus, button:focus-visible, input:focus-visible {
  outline: 3px solid rgba(37, 111, 153, .2);
  outline-offset: 1px;
}
.overall {
  margin-top: 22px;
  padding: 20px;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 8px;
}
.overall h2 { margin: 0 0 12px; font-size: 19px; }
.hidden { display: none !important; }
.source-link { color: var(--focus); }
.badge {
  display: inline-block;
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 2px 7px;
  margin-right: 5px;
  color: var(--muted);
}
@media (max-width: 760px) {
  .topbar-inner, main { width: min(100% - 20px, 1180px); }
  .heading-row { align-items: flex-start; }
  .scene { grid-template-columns: 1fr; }
  .preview { min-height: 0; aspect-ratio: 9 / 16; }
  h1 { font-size: 19px; }
}
@media print {
  .topbar { position: static; }
  .toolbar, .progress-track, .status-row { display: none; }
  body { background: #fff; }
  main { width: 100%; padding: 0; }
  .scene { break-inside: avoid; margin: 0 0 12px; }
}
</style>
</head>
<body>
<header class="topbar">
  <div class="topbar-inner">
    <div class="heading-row">
      <div>
        <h1 id="title"></h1>
        <p class="subtitle" id="subtitle"></p>
      </div>
      <button type="button" class="primary" id="export">Export feedback</button>
    </div>
    <div class="toolbar">
      <button type="button" class="approve-all" id="approve-remaining">Approve remaining</button>
      <button type="button" class="filter active" data-filter="all">All</button>
      <button type="button" class="filter" data-filter="unreviewed">Unreviewed</button>
      <button type="button" class="filter" data-filter="approved">Approved</button>
      <button type="button" class="filter" data-filter="revise">Needs revision</button>
      <label class="file-button" for="import-file">Import feedback</label>
      <input class="hidden" id="import-file" type="file" accept="application/json">
      <button type="button" id="print">Print</button>
    </div>
    <div class="progress-track"><div class="progress-bar" id="progress-bar"></div></div>
    <div class="status-row">
      <span id="progress-text"></span>
      <span id="save-status">Draft saved locally</span>
    </div>
  </div>
</header>
<main>
  <div class="scene-list" id="scene-list"></div>
  <section class="overall">
    <h2>Overall Video Decision</h2>
    <div class="decision-row">
      <label class="decision approved"><input type="radio" name="overall" value="approved">Approve video</label>
      <label class="decision revise"><input type="radio" name="overall" value="revise">Video needs changes</label>
      <label class="decision"><input type="radio" name="overall" value="unreviewed">Not decided</label>
    </div>
    <textarea id="overall-comments" placeholder="Overall comments"></textarea>
  </section>
</main>
<script type="application/json" id="review-data">__REVIEW_JSON__</script>
<script>
(function () {
  "use strict";
  var data = JSON.parse(document.getElementById("review-data").textContent);
  var key = "scene-review:" + data.slug + ":" + data.script_fingerprint;
  var state = { scenes: {}, overall: { decision: "unreviewed", comments: "" } };
  try {
    var saved = JSON.parse(localStorage.getItem(key));
    if (saved && saved.scenes) state = saved;
  } catch (error) {}

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (char) {
      return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char];
    });
  }

  function current(index) {
    var id = String(index);
    if (!state.scenes[id]) state.scenes[id] = { decision: "unreviewed", comments: "" };
    return state.scenes[id];
  }

  function save() {
    localStorage.setItem(key, JSON.stringify(state));
    document.getElementById("save-status").textContent = "Draft saved locally";
    updateProgress();
  }

  function render() {
    document.getElementById("title").textContent = data.title + " - Scene Review";
    document.getElementById("subtitle").textContent =
      data.scenes.length + " scenes | Survey version " + data.schema_version;
    var list = document.getElementById("scene-list");
    data.scenes.forEach(function (scene) {
      var review = current(scene.scene_index);
      var card = document.createElement("article");
      card.className = "scene";
      card.id = "scene-" + scene.scene_number;
      card.dataset.decision = review.decision;
      var preview = scene.preview
        ? '<img src="' + scene.preview + '" alt="Scene ' + scene.scene_number + ' preview">'
        : '<span>Preview unavailable</span>';
      var source = scene.source_url
        ? '<a class="source-link" href="' + esc(scene.source_url) + '" target="_blank" rel="noreferrer">Open source footage</a>'
        : "Generated or local visual";
      card.innerHTML =
        '<div class="preview">' + preview + '</div>' +
        '<div class="scene-body">' +
          '<div class="scene-head"><span class="scene-number">Scene ' + scene.scene_number +
          '</span><span class="timecode">' + esc(scene.timecode) + ' | ' +
          Number(scene.duration_seconds || 0).toFixed(1) + 's</span></div>' +
          '<p class="narration">' + esc(scene.narration) + '</p>' +
          '<div class="meta-block"><span class="meta-label">Visual description</span>' +
          '<p class="meta-text">' + esc(scene.visual_description) + '</p></div>' +
          '<div class="meta-block"><span class="meta-label">Why it was chosen</span>' +
          '<p class="meta-text">' + esc(scene.why_chosen) + '</p></div>' +
          '<details><summary>Render details</summary><div class="render-details">' +
          '<span class="badge">' + esc(scene.visual_function || "visual") + '</span>' +
          '<span class="badge">' + esc(scene.symbol_family || "unspecified") + '</span>' +
          '<span class="badge">' + esc(scene.motion_mode || "motion") + '</span>' +
          '<p>Source ID: ' + esc(scene.source_id || "n/a") + ' | ' + source + '</p>' +
          '</div></details>' +
          '<div class="review-box"><span class="meta-label">Scene decision</span>' +
          '<div class="decision-row">' +
          '<label class="decision approved"><input type="radio" name="decision-' +
          scene.scene_index + '" value="approved">Approve</label>' +
          '<label class="decision revise"><input type="radio" name="decision-' +
          scene.scene_index + '" value="revise">Needs revision</label>' +
          '<label class="decision"><input type="radio" name="decision-' +
          scene.scene_index + '" value="unreviewed">Not reviewed</label></div>' +
          '<textarea data-comment="' + scene.scene_index +
          '" placeholder="Comments for scene ' + scene.scene_number + '">' +
          esc(review.comments) + '</textarea></div>' +
        '</div>';
      list.appendChild(card);
      var selected = card.querySelector('input[value="' + review.decision + '"]');
      if (selected) selected.checked = true;
      card.querySelectorAll('input[type="radio"]').forEach(function (input) {
        input.addEventListener("change", function () {
          current(scene.scene_index).decision = input.value;
          card.dataset.decision = input.value;
          save();
        });
      });
      card.querySelector("textarea").addEventListener("input", function (event) {
        current(scene.scene_index).comments = event.target.value;
        save();
      });
    });

    document.querySelectorAll('input[name="overall"]').forEach(function (input) {
      if (input.value === state.overall.decision) input.checked = true;
      input.addEventListener("change", function () {
        state.overall.decision = input.value;
        save();
      });
    });
    var overallComments = document.getElementById("overall-comments");
    overallComments.value = state.overall.comments || "";
    overallComments.addEventListener("input", function (event) {
      state.overall.comments = event.target.value;
      save();
    });
    updateProgress();
  }

  function updateProgress() {
    var reviewed = 0;
    var approved = 0;
    var revise = 0;
    data.scenes.forEach(function (scene) {
      var decision = current(scene.scene_index).decision;
      if (decision !== "unreviewed") reviewed += 1;
      if (decision === "approved") approved += 1;
      if (decision === "revise") revise += 1;
    });
    var percent = data.scenes.length ? (reviewed / data.scenes.length) * 100 : 0;
    document.getElementById("progress-bar").style.width = percent + "%";
    document.getElementById("progress-text").textContent =
      reviewed + " of " + data.scenes.length + " reviewed | " +
      approved + " approved | " + revise + " revisions";
  }

  function feedbackPayload() {
    return {
      schema_version: data.schema_version,
      slug: data.slug,
      title: data.title,
      script_fingerprint: data.script_fingerprint,
      generated_at: data.generated_at,
      reviewed_at: new Date().toISOString(),
      overall: {
        decision: state.overall.decision || "unreviewed",
        comments: state.overall.comments || ""
      },
      scenes: data.scenes.map(function (scene) {
        var review = current(scene.scene_index);
        return {
          scene_index: scene.scene_index,
          scene_number: scene.scene_number,
          narration: scene.narration,
          visual_description: scene.visual_description,
          why_chosen: scene.why_chosen,
          source_id: scene.source_id,
          decision: review.decision || "unreviewed",
          comments: review.comments || ""
        };
      })
    };
  }

  function exportFeedback() {
    var missingComment = data.scenes.some(function (scene) {
      var review = current(scene.scene_index);
      return review.decision === "revise" && !String(review.comments || "").trim();
    });
    if (missingComment) {
      alert("Please add a comment to every scene marked Needs revision.");
      return;
    }
    var blob = new Blob([JSON.stringify(feedbackPayload(), null, 2) + "\n"],
                        {type: "application/json"});
    var link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = data.slug + "-scene-feedback.json";
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(link.href);
  }

  document.getElementById("export").addEventListener("click", exportFeedback);
  document.getElementById("print").addEventListener("click", function () { window.print(); });
  document.getElementById("approve-remaining").addEventListener("click", function () {
    data.scenes.forEach(function (scene) {
      var review = current(scene.scene_index);
      if (review.decision === "unreviewed") review.decision = "approved";
      var card = document.getElementById("scene-" + scene.scene_number);
      card.dataset.decision = review.decision;
      var input = card.querySelector('input[value="' + review.decision + '"]');
      if (input) input.checked = true;
    });
    save();
  });

  document.querySelectorAll(".filter").forEach(function (button) {
    button.addEventListener("click", function () {
      document.querySelectorAll(".filter").forEach(function (item) {
        item.classList.remove("active");
      });
      button.classList.add("active");
      var filter = button.dataset.filter;
      data.scenes.forEach(function (scene) {
        var card = document.getElementById("scene-" + scene.scene_number);
        card.classList.toggle("hidden",
          filter !== "all" && current(scene.scene_index).decision !== filter);
      });
    });
  });

  document.getElementById("import-file").addEventListener("change", function (event) {
    var file = event.target.files[0];
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function () {
      try {
        var imported = JSON.parse(reader.result);
        if (imported.slug !== data.slug) throw new Error("This feedback belongs to another video.");
        imported.scenes.forEach(function (scene) {
          state.scenes[String(scene.scene_index)] = {
            decision: scene.decision || "unreviewed",
            comments: scene.comments || ""
          };
        });
        state.overall = imported.overall || state.overall;
        localStorage.setItem(key, JSON.stringify(state));
        location.reload();
      } catch (error) {
        alert(error.message || "Could not import that feedback file.");
      }
    };
    reader.readAsText(file);
  });

  render();
})();
</script>
</body>
</html>
"""


def is_current(build_dir):
    script_path = os.path.join(build_dir, "script.json")
    review_path = os.path.join(build_dir, "scene-review.json")
    html_path = os.path.join(build_dir, "scene-review.html")
    if not (os.path.exists(script_path) and os.path.exists(review_path)
            and os.path.exists(html_path)):
        return False
    try:
        with open(script_path, encoding="utf-8") as handle:
            script = json.load(handle)
        with open(review_path, encoding="utf-8") as handle:
            saved = json.load(handle)
    except (OSError, ValueError, TypeError):
        return False
    return saved.get("script_fingerprint") == _fingerprint(script)


def generate(build_dir, video=None):
    script_path = os.path.join(build_dir, "script.json")
    with open(script_path, encoding="utf-8") as handle:
        script = json.load(handle)
    scenes = script.get("scenes") or []
    if not scenes:
        raise ValueError("script.json has no scenes")

    selected_video = _video_path(build_dir, video)
    review = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "slug": script.get("slug") or os.path.basename(os.path.abspath(build_dir)),
        "title": script.get("title") or "Untitled Video",
        "genre": script.get("genre"),
        "script_fingerprint": _fingerprint(script),
        "video_file": os.path.basename(selected_video) if selected_video else None,
        "scenes": [],
        "overall": {"decision": "unreviewed", "comments": ""},
    }
    preview_count = 0
    for index, scene in enumerate(scenes):
        preview = _preview_data_uri(selected_video, scene)
        if preview:
            preview_count += 1
        review["scenes"].append(_scene_payload(scene, index, preview))
    if selected_video and preview_count != len(scenes):
        raise RuntimeError(
            f"generated {preview_count}/{len(scenes)} scene previews; "
            "verify FFmpeg and the selected review video"
        )

    metadata = copy.deepcopy(review)
    for scene in metadata["scenes"]:
        scene.pop("preview", None)

    json_path = os.path.join(build_dir, "scene-review.json")
    html_path = os.path.join(build_dir, "scene-review.html")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, ensure_ascii=True)
        handle.write("\n")
    embedded = json.dumps(review, ensure_ascii=True).replace("</", "<\\/")
    rendered = HTML_TEMPLATE.replace("__TITLE__", html.escape(review["title"])).replace(
        "__REVIEW_JSON__", embedded)
    with open(html_path, "w", encoding="utf-8") as handle:
        handle.write(rendered)
    print(f"scene review: {html_path} ({len(scenes)} scenes)")
    return html_path, json_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="generate", choices=["generate"])
    parser.add_argument("build_dir")
    parser.add_argument("--video")
    args = parser.parse_args()
    generate(args.build_dir, args.video)


if __name__ == "__main__":
    main()
