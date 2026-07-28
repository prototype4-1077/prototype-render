"""Publish explicitly requested finished renders to a Facebook Page.

A committed receipt prevents duplicate uploads. Use ``--force`` only for an
intentional repost. The 16:9 master remains the preferred Facebook feed asset.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = os.environ.get("FB_REPO", "prototype-video/Prototype-Video")
API = "https://graph-video.facebook.com/v25.0"
QUEUE = HERE / "fb_publish_queue.json"
RESULT = HERE / "fb_published_result.json"


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def atomic_json(path: Path, payload: Any) -> None:
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def normalized_history() -> dict[str, dict[str, Any]]:
    raw = load_json(RESULT, {}) or {}
    output: dict[str, dict[str, Any]] = {}
    for slug, value in raw.items() if isinstance(raw, dict) else []:
        if isinstance(value, str):
            output[str(slug)] = {
                "video_id": value,
                "url": f"https://www.facebook.com/watch/?v={value}",
            }
        elif isinstance(value, dict) and value.get("video_id"):
            output[str(slug)] = dict(value)
    return output


def download_final(slug: str) -> str:
    out = f"/tmp/{slug}.mp4"
    last: subprocess.CalledProcessError | None = None
    for pattern in ("final_youtube.mp4", "final.mp4"):
        try:
            subprocess.run(
                ["gh", "release", "download", f"video-{slug}", "-R", REPO,
                 "-p", pattern, "-O", out, "--clobber"],
                check=True,
                env={**os.environ},
            )
            return out
        except subprocess.CalledProcessError as error:
            last = error
    if last is None:
        raise RuntimeError(f"no release asset pattern attempted for {slug}")
    raise last


def upload(slug: str, meta: dict[str, Any], page_id: str, token: str) -> str:
    path = download_final(slug)
    result = subprocess.run(
        [
            "curl", "-sS", "-X", "POST", f"{API}/{page_id}/videos",
            "-F", f"access_token={token}",
            "-F", f"title={meta.get('title', '')}",
            "-F", f"description={meta.get('description', '')}",
            "-F", f"source=@{path}",
        ],
        capture_output=True,
        text=True,
    )
    try:
        response = json.loads(result.stdout)
    except ValueError as error:
        raise RuntimeError(
            f"Facebook upload failed for {slug}: {result.stdout[:400]} {result.stderr[:200]}"
        ) from error
    if result.returncode != 0 or "id" not in response:
        raise RuntimeError(f"Facebook upload error for {slug}: {json.dumps(response)[:500]}")
    return str(response["id"])


def publish(slugs: list[str], *, force: bool = False) -> dict[str, dict[str, Any]]:
    if not slugs:
        raise ValueError("explicit slug required; refusing to publish the entire queue")
    page_id = os.environ["FB_PAGE_ID"]
    token = os.environ["FB_PAGE_TOKEN"]
    queue = load_json(QUEUE, {}) or {}
    history = normalized_history()
    missing = [slug for slug in slugs if slug not in queue]
    if missing:
        raise KeyError("not in Facebook publish queue: " + ", ".join(missing))

    for slug in slugs:
        if slug in history and not force:
            print(f"SKIP already published {slug} -> {history[slug].get('url')}")
            continue
        meta = queue[slug]
        video_id = upload(slug, meta, page_id, token)
        record = {
            "video_id": video_id,
            "url": f"https://www.facebook.com/watch/?v={video_id}",
            "published_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
            "title": meta.get("title"),
            "forced": bool(force),
        }
        history[slug] = record
        atomic_json(RESULT, history)
        print(f"PUBLISHED {slug} -> {record['url']}")
    return history


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="allow an intentional duplicate upload")
    parser.add_argument("slugs", nargs="*")
    args = parser.parse_args(argv)
    result = publish(args.slugs, force=args.force)
    print("ALL DONE:", json.dumps({slug: result.get(slug) for slug in args.slugs}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
