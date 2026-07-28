"""Publish explicitly requested finished renders to YouTube as Public.

Publishing is idempotent by default. A committed receipt is checked before any
upload, updated atomically after every successful video, and may be bypassed only
with the explicit ``--force`` flag. The YouTube-specific master is preferred.
The established analytics registry is imported as legacy receipt evidence so the
existing catalog is protected immediately.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import urllib.parse
import urllib.request
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = os.environ.get("GH_REPO", "prototype-video/Prototype-Video")
QUEUE = HERE / "yt_publish_queue.json"
RESULT = HERE / "yt_published_result.json"
LEGACY_RESULT = HERE / "published_videos.json"


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def atomic_json(path: Path, payload: Any) -> None:
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _record(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        return {"video_id": value, "url": f"https://youtube.com/watch?v={value}"}
    if not isinstance(value, dict):
        return None
    video_id = value.get("video_id") or value.get("youtube_id")
    if not video_id and not value.get("published_without_id"):
        return None
    record = dict(value)
    if video_id:
        record["video_id"] = str(video_id)
        record["url"] = value.get("url") or f"https://youtube.com/watch?v={video_id}"
    else:
        record["published_without_id"] = True
        record.setdefault("url", None)
    record["published_at"] = value.get("published_at") or value.get("published")
    record["receipt_source"] = value.get("receipt_source") or "legacy_analytics_registry"
    return record


def normalized_history() -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for source in (load_json(LEGACY_RESULT, {}) or {}, load_json(RESULT, {}) or {}):
        if not isinstance(source, dict):
            continue
        for slug, value in source.items():
            record = _record(value)
            if record:
                output[str(slug)] = record
    return output


def access_token() -> str:
    data = urllib.parse.urlencode({
        "client_id": os.environ["YT_CLIENT_ID"],
        "client_secret": os.environ["YT_CLIENT_SECRET"],
        "refresh_token": os.environ["YT_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }).encode()
    request = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
    response = json.load(urllib.request.urlopen(request, timeout=30))
    return str(response["access_token"])


def download_final(slug: str, meta: dict[str, Any] | None = None) -> str:
    """Download the finished video for a queue entry.

    A Short reuses another slug's release: set "release_tag" and "source_asset"
    in the queue entry (e.g. final_portrait.mp4) and it will be fetched instead.
    """
    meta = meta or {}
    tag = str(meta.get("release_tag") or f"video-{slug}")
    patterns = ([str(meta["source_asset"])] if meta.get("source_asset")
                else ["final_youtube.mp4", "final.mp4"])
    out = f"/tmp/{slug}.mp4"
    last: subprocess.CalledProcessError | None = None
    for pattern in patterns:
        try:
            subprocess.run(
                ["gh", "release", "download", tag, "-R", REPO,
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


def upload(path: str, meta: dict[str, Any], token: str) -> str:
    size = os.path.getsize(path)
    body = {
        "snippet": {
            "title": str(meta["title"])[:100],
            "description": str(meta["description"])[:4900],
            "tags": meta.get("tags", []),
            "categoryId": "22",
        },
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
    }
    request = urllib.request.Request(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(size),
            "X-Upload-Content-Type": "video/mp4",
        },
    )
    uri = urllib.request.urlopen(request, timeout=30).headers["Location"]
    with open(path, "rb") as handle:
        data = handle.read()
    put = urllib.request.Request(
        uri,
        data=data,
        method="PUT",
        headers={
            "Authorization": "Bearer " + token,
            "Content-Range": f"bytes 0-{size-1}/{size}",
            "Content-Type": "video/mp4",
        },
    )
    response = json.load(urllib.request.urlopen(put, timeout=300))
    return str(response["id"])


def set_thumbnail(video_id: str, slug: str, token: str, meta: dict[str, Any] | None = None) -> bool:
    """Best-effort: generate + set a custom thumbnail. Never breaks a publish."""
    try:
        import thumbnail
        meta_local = meta or {}
        build_slug = str(meta_local.get("build_slug") or slug)
        thumb = thumbnail.generate(build_slug, HERE.parent / "build" / build_slug,
                                   portrait=bool(meta_local.get("portrait")))
        with open(thumb, "rb") as handle:
            data = handle.read()
        req = urllib.request.Request(
            f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={video_id}",
            data=data, method="POST",
            headers={"Authorization": "Bearer " + token, "Content-Type": "image/jpeg"},
        )
        urllib.request.urlopen(req, timeout=120)
        print(f"THUMBNAIL set for {slug}", flush=True)
        return True
    except Exception as error:  # noqa: BLE001
        print(f"WARN thumbnail failed for {slug}: {error}", flush=True)
        return False


def short_meta(slug: str, meta: dict[str, Any]) -> dict[str, Any]:
    """Derive the Short's metadata from the long-form entry."""
    title = str(meta.get("title") or slug)
    desc = str(meta.get("description") or "")
    head = desc.split("\n")[0][:400]
    tags = list(meta.get("tags") or [])
    return {
        "title": (title + " #Shorts")[:100],
        "description": (head + "\n#Shorts " + " ".join("#" + str(x).replace(" ", "")
                                                        for x in tags[:5]))[:4900],
        "tags": (["Shorts"] + tags)[:15],
        "release_tag": f"video-{slug}",
        "source_asset": "final.mp4",
        "build_slug": slug,
        "portrait": True,
    }


def release_has_portrait(slug: str) -> bool:
    try:
        out = subprocess.run(
            ["gh", "release", "view", f"video-{slug}", "-R", REPO, "--json", "assets"],
            check=True, capture_output=True, text=True, env={**os.environ},
        )
        names = {a.get("name") for a in json.loads(out.stdout).get("assets", [])}
        return "final.mp4" in names
    except Exception:  # noqa: BLE001
        return False


def publish(slugs: list[str], *, force: bool = False) -> dict[str, dict[str, Any]]:
    if not slugs:
        raise ValueError("explicit slug required; refusing to publish the entire queue")
    queue = load_json(QUEUE, {}) or {}
    history = normalized_history()
    missing = [slug for slug in slugs if slug not in queue]
    if missing:
        raise KeyError("not in YouTube publish queue: " + ", ".join(missing))

    pending = [slug for slug in slugs if force or slug not in history]
    for slug in slugs:
        if slug not in pending:
            destination = history[slug].get("url") or "verified prior upload; video ID not recorded"
            print(f"SKIP already published {slug} -> {destination}", flush=True)
    if not pending:
        atomic_json(RESULT, history)
        return history

    token = access_token()
    for slug in pending:
        meta = queue[slug]
        path = download_final(slug, meta)
        video_id = upload(path, meta, token)
        record = {
            "video_id": video_id,
            "url": f"https://youtube.com/watch?v={video_id}",
            "published_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
            "title": meta.get("title"),
            "forced": bool(force),
            "receipt_source": "publisher",
        }
        history[slug] = record
        atomic_json(RESULT, history)
        print(f"PUBLISHED {slug} -> {record['url']}", flush=True)
        set_thumbnail(video_id, slug, token, meta)

        # Standing rule: every video also ships as a vertical Short.
        short_slug = f"{slug}-short"
        if (not slug.endswith("-short") and short_slug not in history
                and release_has_portrait(slug)):
            try:
                smeta = queue.get(short_slug) or short_meta(slug, meta)
                spath = download_final(short_slug, smeta)
                svid = upload(spath, smeta, token)
                history[short_slug] = {
                    "video_id": svid,
                    "url": f"https://youtube.com/watch?v={svid}",
                    "published_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
                    "title": smeta.get("title"),
                    "forced": bool(force),
                    "receipt_source": "publisher_auto_short",
                }
                atomic_json(RESULT, history)
                print(f"PUBLISHED {short_slug} -> {history[short_slug]['url']}", flush=True)
                set_thumbnail(svid, short_slug, token, smeta)
            except Exception as error:  # noqa: BLE001 - Short must not break the main post
                print(f"WARN auto-Short failed for {slug}: {error}", flush=True)
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
