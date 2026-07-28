"""Refresh public YouTube performance snapshots for verified publish receipts.

Uses ``YT_API_KEY`` when available, otherwise the existing OAuth refresh token.
If the credential lacks read permission, the collector writes an explicit status
record and returns a nonzero code without fabricating statistics.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RECEIPTS = HERE / "yt_published_result.json"
LEGACY = HERE / "published_videos.json"
STATUS = HERE / "youtube_stats_status.json"
API = "https://www.googleapis.com/youtube/v3/videos"


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def record(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        return {"video_id": value}
    if not isinstance(value, dict):
        return None
    video_id = value.get("video_id") or value.get("youtube_id")
    if not video_id:
        return None
    return {
        **value,
        "video_id": str(video_id),
        "published_at": value.get("published_at") or value.get("published"),
    }


def receipts() -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for payload in (load(LEGACY, {}) or {}, load(RECEIPTS, {}) or {}):
        if not isinstance(payload, dict):
            continue
        for slug, value in payload.items():
            item = record(value)
            if item:
                output[str(slug)] = item
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


def authorization() -> tuple[dict[str, str], dict[str, str], str]:
    key = os.environ.get("YT_API_KEY")
    if key:
        return {}, {"key": key}, "api_key"
    required = ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")
    if all(os.environ.get(name) for name in required):
        return {"Authorization": "Bearer " + access_token()}, {}, "oauth_refresh_token"
    raise RuntimeError("Configure YT_API_KEY or YT_CLIENT_ID/YT_CLIENT_SECRET/YT_REFRESH_TOKEN")


def batches(items: list[str], size: int = 50):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def fetch(ids: list[str], headers: dict[str, str], params: dict[str, str]) -> list[dict[str, Any]]:
    output = []
    for group in batches(ids):
        query = urllib.parse.urlencode({
            "part": "snippet,statistics,contentDetails,status",
            "id": ",".join(group),
            **params,
        })
        request = urllib.request.Request(f"{API}?{query}", headers=headers)
        payload = json.load(urllib.request.urlopen(request, timeout=60))
        output.extend(item for item in (payload.get("items") or []) if isinstance(item, dict))
    return output


def integer(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_time(value: Any) -> dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except ValueError:
        try:
            return dt.datetime.fromisoformat(text[:10]).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            return None


def rates(stats: dict[str, Any], published_at: Any, now: dt.datetime) -> dict[str, float | None]:
    views = integer(stats.get("viewCount"))
    likes = integer(stats.get("likeCount"))
    comments = integer(stats.get("commentCount"))
    published = parse_time(published_at)
    age_days = max((now - published).total_seconds() / 86400.0, 1 / 24) if published else None
    return {
        "video_age_days": round(age_days, 4) if age_days is not None else None,
        "views_per_day": round(views / age_days, 4) if views is not None and age_days else None,
        "likes_per_100_views": round(likes * 100 / views, 4) if likes is not None and views else None,
        "comments_per_1000_views": round(comments * 1000 / views, 4) if comments is not None and views else None,
    }


def refresh(repo_root: Path = ROOT) -> dict[str, Any]:
    catalog = receipts()
    ids = [item["video_id"] for item in catalog.values()]
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    status: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": now.isoformat(),
        "receipt_count": len(catalog),
        "video_id_count": len(ids),
        "updated": [],
        "missing_from_api": [],
    }
    try:
        headers, params, auth_mode = authorization()
        status["auth_mode"] = auth_mode
        items = fetch(ids, headers, params)
    except (RuntimeError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
        body = ""
        if isinstance(error, urllib.error.HTTPError):
            try:
                body = error.read().decode("utf-8", errors="replace")[:1000]
            except Exception:
                body = ""
        status.update({
            "status": "permission_or_network_error",
            "error_type": type(error).__name__,
            "error": str(error),
            "response_body": body,
            "required_action": (
                "Provide YT_API_KEY or refresh the OAuth grant with a YouTube read-capable scope. "
                "No statistics were fabricated."
            ),
        })
        atomic_json(STATUS, status)
        return status

    by_id = {str(item.get("id")): item for item in items if item.get("id")}
    for slug, receipt in catalog.items():
        video_id = receipt["video_id"]
        item = by_id.get(video_id)
        if not item:
            status["missing_from_api"].append(slug)
            continue
        statistics = item.get("statistics") or {}
        snippet = item.get("snippet") or {}
        content = item.get("contentDetails") or {}
        output = {
            "schema_version": 1,
            "snapshot_at": now.isoformat(),
            "source": "youtube_data_api_v3_videos_list",
            "slug": slug,
            "video_id": video_id,
            "title": snippet.get("title") or receipt.get("title"),
            "youtube_published_at": snippet.get("publishedAt"),
            "receipt_published_at": receipt.get("published_at"),
            "duration_iso8601": content.get("duration"),
            "privacy_status": (item.get("status") or {}).get("privacyStatus"),
            "views": integer(statistics.get("viewCount")),
            "likes": integer(statistics.get("likeCount")),
            "comments": integer(statistics.get("commentCount")),
            "favorites": integer(statistics.get("favoriteCount")),
            **rates(statistics, snippet.get("publishedAt") or receipt.get("published_at"), now),
            "interpretation_boundary": (
                "Public counts are age-normalized screening signals. They do not include retention, "
                "impressions, watch time, traffic source, or causal creative attribution."
            ),
        }
        target = repo_root / "build" / slug / "yt_stats.json"
        atomic_json(target, output)
        status["updated"].append(slug)
    status.update({
        "status": "success",
        "api_item_count": len(items),
        "updated_count": len(status["updated"]),
        "missing_count": len(status["missing_from_api"]),
    })
    atomic_json(STATUS, status)
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(ROOT))
    args = parser.parse_args(argv)
    report = refresh(Path(args.repo_root).resolve())
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report.get("status") == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
