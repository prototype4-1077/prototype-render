"""Nightly audience-retention sync: YouTube Analytics -> per-scene learning.

Reads pipeline/published_videos.json (slug -> youtube_id, mapped via
`learn.py published <slug> <video_id>`), pulls each video's 100-point audience
retention curve plus summary stats, writes build/<slug>/retention.json and
yt_stats.json, then applies learn.audience() and refreshes WHATS_WORKING.md.
Exits 0 with a notice when credentials are absent so the scheduled workflow
stays green before setup. Setup guide: pipeline/ANALYTICS.md."""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import learn  # noqa: E402

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://youtubeanalytics.googleapis.com/v2/reports"


def access_token():
    cid = os.environ.get("YT_CLIENT_ID")
    sec = os.environ.get("YT_CLIENT_SECRET")
    ref = os.environ.get("YT_REFRESH_TOKEN")
    if not (cid and sec and ref):
        return None
    body = urllib.parse.urlencode({
        "client_id": cid, "client_secret": sec,
        "refresh_token": ref, "grant_type": "refresh_token"}).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=body), timeout=30) as r:
        return json.load(r)["access_token"]


def query(token, video_id, dimensions, metrics):
    params = {"ids": "channel==MINE", "startDate": "2020-01-01",
              "endDate": date.today().isoformat(), "metrics": metrics,
              "filters": f"video=={video_id}"}
    if dimensions:
        params["dimensions"] = dimensions
    req = urllib.request.Request(f"{API}?{urllib.parse.urlencode(params)}",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def main():
    token = access_token()
    if not token:
        print("analytics: YT_CLIENT_ID/YT_CLIENT_SECRET/YT_REFRESH_TOKEN not set; "
              "see pipeline/ANALYTICS.md")
        return 0
    pub = os.path.join(HERE, "published_videos.json")
    if not os.path.exists(pub):
        print("analytics: nothing mapped yet; after each upload run "
              "`python3 pipeline/learn.py published <slug> <video_id>`")
        return 0
    with open(pub) as f:
        published = json.load(f)
    for slug, info in published.items():
        vid = info.get("youtube_id") if isinstance(info, dict) else str(info)
        bd = os.path.normpath(os.path.join(HERE, "..", "build", slug))
        if not os.path.isdir(bd):
            print(f"analytics: {slug}: no build dir, skipping")
            continue
        try:
            rows = query(token, vid, "elapsedVideoTimeRatio",
                         "audienceWatchRatio,relativeRetentionPerformance").get("rows") or []
            stats = query(token, vid, "",
                          "views,estimatedMinutesWatched,averageViewDuration,"
                          "averageViewPercentage").get("rows") or []
        except Exception as exc:
            print(f"analytics: {slug}: API error: {exc}")
            continue
        if not rows:
            print(f"analytics: {slug}: no retention rows yet")
            continue
        payload = {"video_id": vid,
                   "elapsed": [r[0] for r in rows],
                   "watch_ratio": [r[1] for r in rows],
                   "relative_performance": [r[2] for r in rows]}
        rpath = os.path.join(bd, "retention.json")
        with open(rpath, "w") as f:
            json.dump(payload, f, indent=1)
        if stats:
            with open(os.path.join(bd, "yt_stats.json"), "w") as f:
                json.dump(dict(zip(
                    ["views", "minutes_watched", "avg_view_s", "avg_view_pct"],
                    stats[0])), f, indent=1)
        try:
            learn.audience(bd, rpath)
        except Exception as exc:
            print(f"analytics: {slug}: learning error: {exc}")
    learn.digest()
    return 0


if __name__ == "__main__":
    sys.exit(main())
