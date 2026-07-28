"""Generate semantically exact custom motion scenes for Pattern Wearing Matter.

This deterministic scene source bypasses broad-topic stock selection. The generated
clips still pass through the standard TikTok Video Pipeline for captions, music,
voice mastering, Governor supervision, quality checks, artifacts, and Releases.
"""
from pathlib import Path
import importlib.util
import json
import sys

import motion


AUDIT_FAMILIES = (
    "identity", "object_tool", "nature", "nature", "geometry",
    "identity", "time_memory", "geometry", "transformation", "object_tool",
    "transformation", "object_tool", "object_tool", "architecture", "language",
    "world_scale", "nature", "identity", "geometry", "light_atmosphere",
)

# These describe the actual deterministic frame mechanisms in vocabulary the
# pipeline's long-standing symbol auditor understands. They are not stock-search
# prompts and cannot change the rendered picture.
AUDIT_QUERIES = (
    "faceless mannequin outline continuously rebuilt from moving particles while PATTERN remains stable",
    "key and household bills return to the same owner while OBJECT is questioned",
    "river water particles change inside one unmistakable whirlpool",
    "river water enters and leaves one persistent whirlpool form",
    "spiral sustained by movement pressure gravity and shape",
    "transparent masks BODY THOUGHTS and BELIEFS slide and change around one continuing outline",
    "archive drawers for CELLS MEMORIES PASSWORDS and OPINIONS change around ME",
    "geometric pieces and connecting lines change while one relationship remains",
    "rearranging particles turn into and rebuild one standing outline",
    "radio piano speaker and waveform show one continuing song",
    "dissolving instrument turns into the same moving waveform in another location",
    "radio receiver outline carries a larger pattern waveform",
    "paper mail bills anchor a radio router signal joke",
    "glowing thought marker crosses a doorway into a kitchen and dissolves",
    "printed labels MEMORIES TENSIONS JOKES LOYALTIES EXPECTATIONS form one network",
    "aerial city skyline remains while individual brick cells are replaced",
    "fire consumes wood while the flame process continues",
    "costume outline fades while a luminous dance path remains",
    "cube marked THING transforms into a connected geometric PATTERN network",
    "instrument silhouettes fade beneath expanding light waves while reality listens",
)


def load_renderer(repo_root: Path):
    source = repo_root / "build" / "pattern-wearing-matter-semantic-pipeline" / "render_semantic_assets.py"
    spec = importlib.util.spec_from_file_location("pwm_semantic_assets", source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load semantic renderer: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generate(build_dir: str | Path) -> None:
    build = Path(build_dir).resolve()
    repo_root = Path(__file__).resolve().parents[1]
    module = load_renderer(repo_root)
    module.generate_all(build)
    script_path = build / "script.json"
    script = json.loads(script_path.read_text(encoding="utf-8"))
    scenes = script["scenes"]
    if len(scenes) != len(AUDIT_FAMILIES):
        raise RuntimeError(f"semantic scene contract expected {len(AUDIT_FAMILIES)} scenes; found {len(scenes)}")
    for index, scene in enumerate(scenes):
        clip = build / f"clip_{index:02d}.mp4"
        if not clip.exists() or clip.stat().st_size < 100_000:
            raise RuntimeError(f"semantic clip missing or undersized: {clip}")
        evidence = motion.temporal_evidence(str(clip))
        if not evidence.get("passes"):
            raise RuntimeError(f"semantic clip {index} failed temporal-motion verification: {evidence}")
        evidence["provenance"] = "deterministic evolving frame sequence"
        scene.update({
            "clip": str(clip),
            "motion_kind": "video",
            "motion_mode": "recorded",
            "motion_source": "deterministic_semantic_animation",
            "motion_verified": True,
            "motion_evidence": evidence,
            "semantic_visual_locked": True,
            "symbol_family": AUDIT_FAMILIES[index],
            "symbol_family_source": "semantic_renderer",
            "symbol_query": AUDIT_QUERIES[index],
            "query": AUDIT_QUERIES[index],
        })
        scene.pop("human_role", None)
    script_path.write_text(json.dumps(script, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    generate(sys.argv[1])
