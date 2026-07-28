"""Extra footage providers beyond Pexels - all keyless and free.
Each returns Pexels-shaped candidates:
{ "id": "<ns>:<id>", "duration": s, "image": thumb_url, "source": ns,
  "video_files": [{"link":..., "width":..., "height":...}] }
Every provider is wrapped: slow or broken sources return [] and never stall a build.
Optional: set PIXABAY_API_KEY (free account) to add Pixabay as a fourth source."""
import html, json, os, re, urllib.parse, urllib.request

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}


def _get(url, timeout=12):
    req = urllib.request.Request(url, headers=UA)
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def _text(url, timeout=18):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read().decode(
        "utf-8", errors="replace"
    )


MIXKIT_TAG_RULES = (
    ("video-call", ("video call", "live video", "call faces")),
    ("road", ("arrow", "arrows", "crossroad", "fork in road", "pathway", "signpost", "direction")),
    ("abstract", ("nested ring", "illuminated ring", "recursive", "geometry", "geometric", "spectrum", "wavelength")),
    ("city", ("city", "civilization", "public square", "urban", "globe reflected")),
    ("travel", ("compass", "folded map", "route", "territory")),
    ("vintage", ("record needle", "vinyl record", "old photograph", "photo album", "film projector")),
    ("selfie", ("selfie", "retakes", "posed photo")),
    ("pregnancy", ("pregnant", "expectant", "mother", "belly")),
    ("surveillance", ("surveillance", "security camera", "cctv")),
    ("meeting", ("meeting", "coworker", "office", "raises hand")),
    ("crowd", ("crowd", "plaza", "many people", "public square")),
    ("dancing", ("dance", "dancing")),
    ("greenhouse", ("greenhouse",)),
    ("gardening", ("garden", "gardener", "seedling", "soil")),
    ("painting", ("canvas", "easel", "painting", "artist")),
    ("shopping", ("store", "shop", "shelf", "merchandise")),
    ("door", ("door", "doorway")),
    ("sunrise", ("sunrise", "dawn")),
    ("performance", ("perform", "stage", "rehearse", "speaking")),
    ("mirror", ("mirror", "jacket", "clothing", "magnifying lens", "magnifying glass", "reflection")),
    ("smartphone", ("smartphone", "phone", "social media", "screen")),
    ("writing", ("write", "writing", "notebook", "sentence", "paper")),
    ("home", ("room", "home", "living room", "bedroom")),
)

COVERR_TAG_FALLBACKS = {
    "greenhouse": "farmer",
    "gardening": "farmer",
    "meeting": "business",
    "sunrise": "nature",
    "performance": "performance",
    "surveillance": "security",
    "painting": "canvas",
    "pregnancy": "pregnant",
    "crowd": "people",
    "video-call": "video-call",
}


def _mixkit_tag(query):
    lowered = query.lower()
    for tag, phrases in MIXKIT_TAG_RULES:
        if any(phrase in lowered for phrase in phrases):
            return tag
    return "people"


def mixkit(query, limit=12, tag=None):
    """Mixkit free-license stock footage, scraped from public discover pages.

    Mixkit does not require an API credential for its public catalog or 720p
    downloads.  Discover pages expose stable item IDs and direct preview assets;
    those IDs are persisted as ``mixkit:<id>`` for reproducible rebuilds.
    """
    try:
        tag = tag or _mixkit_tag(query)
        page = _text(f"https://mixkit.co/free-stock-video/discover/{tag}/")
        matches = re.findall(
            r'href="(/free-stock-video/([a-z0-9-]+)-(\d+)/)"[^>]*>'
            r'\s*([^<]+?)\s*</a>',
            page,
            flags=re.IGNORECASE,
        )
        out, seen = [], set()
        for path, _slug, raw_id, title in matches:
            if raw_id in seen:
                continue
            seen.add(raw_id)
            title = " ".join(html.unescape(title).split())
            out.append({
                "id": f"mixkit:{raw_id}",
                "duration": 10,
                "image": (
                    f"https://assets.mixkit.co/videos/{raw_id}/"
                    f"{raw_id}-thumb-360-0.jpg"
                ),
                "source": "mixkit",
                "title": title,
                "description": title,
                "url": f"https://mixkit.co{path}",
                "video_files": [
                    {
                        "link": (
                            f"https://assets.mixkit.co/videos/{raw_id}/"
                            f"{raw_id}-720.mp4"
                        ),
                        "width": 1280,
                        "height": 720,
                    },
                    {
                        "link": (
                            f"https://assets.mixkit.co/videos/{raw_id}/"
                            f"{raw_id}-360.mp4"
                        ),
                        "width": 640,
                        "height": 360,
                    },
                ],
            })
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


def coverr(query, limit=16, tag=None):
    """Coverr free stock via public topic pages and direct HD renditions."""
    try:
        raw_tag = tag or _mixkit_tag(query)
        tag = COVERR_TAG_FALLBACKS.get(raw_tag, raw_tag)
        page = _text(f"https://coverr.co/stock-video-footage/{tag}", timeout=25)
        slugs = re.findall(
            r"https://cdn\.coverr\.co/videos/([^/\"\\]+)/720p\.mp4",
            page,
            flags=re.IGNORECASE,
        )
        out, seen = [], set()
        for slug in slugs:
            if slug in seen or "premium" in slug or slug.startswith("user-ai-generation"):
                continue
            seen.add(slug)
            title_slug = re.sub(r"^coverr-", "", slug)
            title_slug = re.sub(r"-\d+$", "", title_slug)
            title = title_slug.replace("-", " ").strip().title()
            out.append({
                "id": f"coverr:{slug}",
                "duration": 10,
                # This is Coverr's public thumbnail for the exact selected
                # video.  still_reference.py saves it as the continuity frame
                # before any generated/supplied still is enhanced.
                "image": f"https://cdn.coverr.co/videos/{slug}/thumbnail?width=640",
                "source": "coverr",
                "title": title,
                "description": title,
                "url": f"https://coverr.co/videos/{slug}",
                "video_files": [
                    {
                        "link": f"https://cdn.coverr.co/videos/{slug}/1080p.mp4",
                        "width": 1920,
                        "height": 1080,
                    },
                    {
                        "link": f"https://cdn.coverr.co/videos/{slug}/720p.mp4",
                        "width": 1280,
                        "height": 720,
                    },
                    {
                        "link": f"https://cdn.coverr.co/videos/{slug}/360p.mp4",
                        "width": 640,
                        "height": 360,
                    },
                ],
            })
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []


def nasa(q, limit=3):
    """NASA Image & Video Library - stunning space footage, public domain, keyless."""
    try:
        d = _get(f"https://images-api.nasa.gov/search?q={urllib.parse.quote(q)}"
                 f"&media_type=video&page_size={limit}")
        out = []
        for it in d["collection"]["items"][:limit]:
            md = it["data"][0]
            thumb = next((l["href"] for l in it.get("links", []) if l.get("rel") == "preview"), None)
            try:
                files = _get(urllib.parse.quote(it["href"], safe=":/"))
            except Exception:
                continue
            mp4s = [urllib.parse.quote(u.replace("http://", "https://"), safe=":/~")
                    for u in files if u.endswith(".mp4")]
            pick = next((u for u in mp4s if "~large" in u), None) or \
                   next((u for u in mp4s if "~medium" in u), None) or (mp4s[0] if mp4s else None)
            if pick and thumb:
                out.append({"id": f"nasa:{md['nasa_id']}", "duration": 10, "image": thumb,
                            "source": "nasa",
                            "video_files": [{"link": pick, "width": 1920, "height": 1080}]})
        return out
    except Exception:
        return []


def wikimedia(q, limit=4):
    """Wikimedia Commons video search (webm originals; ffmpeg handles them fine)."""
    try:
        d = _get("https://commons.wikimedia.org/w/api.php?action=query&generator=search"
                 f"&gsrsearch=filetype:video%20{urllib.parse.quote(q)}&gsrlimit={limit}"
                 "&gsrnamespace=6&prop=videoinfo&viprop=url|size&format=json")
        out = []
        for p in (d.get("query", {}).get("pages", {}) or {}).values():
            vi = (p.get("videoinfo") or [{}])[0]
            u, w, h = vi.get("url"), vi.get("width", 0), vi.get("height", 0)
            if not u or w < 960:
                continue
            thumb = (f"https://commons.wikimedia.org/w/index.php?title=Special:Redirect/file/"
                     f"{urllib.parse.quote(p['title'].replace('File:',''))}&width=320")
            out.append({"id": f"wm:{p['pageid']}", "duration": 10, "image": thumb,
                        "source": "wikimedia",
                        "video_files": [{"link": u, "width": w, "height": h}]})
        return out
    except Exception:
        return []


def prelinger(q, limit=3):
    """Internet Archive Prelinger collection - vintage film, perfect for eerie/dmt looks."""
    try:
        d = _get("https://archive.org/advancedsearch.php?q="
                 + urllib.parse.quote(f"collection:prelinger AND mediatype:movies AND {q}")
                 + f"&fl%5B%5D=identifier&rows={limit}&output=json")
        out = []
        for doc in d["response"]["docs"][:limit]:
            ident = doc["identifier"]
            try:
                md = _get(f"https://archive.org/metadata/{ident}")
            except Exception:
                continue
            mp4s = sorted((f for f in md.get("files", []) if f["name"].endswith(".mp4")),
                          key=lambda f: -int(f.get("size", 0) or 0))
            if not mp4s:
                continue
            f0 = mp4s[0]
            out.append({"id": f"ia:{ident}", "duration": 12,
                        "image": f"https://archive.org/services/img/{ident}",
                        "source": "prelinger",
                        "video_files": [{"link": f"https://archive.org/download/{ident}/"
                                                 f"{urllib.parse.quote(f0['name'])}",
                                         "width": 1280, "height": 720}]})
        return out
    except Exception:
        return []


def pixabay(q, limit=5):
    """Pixabay (only if free PIXABAY_API_KEY is set - never required)."""
    key = os.environ.get("PIXABAY_API_KEY")
    if not key:
        return []
    try:
        d = _get(f"https://pixabay.com/api/videos/?key={key}&q={urllib.parse.quote(q)}"
                 f"&per_page={limit}&safesearch=true")
        out = []
        for h in d.get("hits", []):
            vs = h.get("videos", {})
            best = vs.get("large") or vs.get("medium") or {}
            if not best.get("url"):
                continue
            out.append({"id": f"pb:{h['id']}", "duration": h.get("duration", 10),
                        "image": best.get("thumbnail", ""), "source": "pixabay",
                        "video_files": [{"link": best["url"], "width": best.get("width", 1920),
                                         "height": best.get("height", 1080)}]})
        return out
    except Exception:
        return []


SPACE_WORDS = ("space", "nebula", "galaxy", "cosmos", "cosmic", "stars", "planet",
               "aurora", "moon", "eclipse", "milky way", "universe")
VINTAGE_WORDS = ("vintage", "retro", "archive", "old film", "16mm", "8mm")


def supplement(q, genre=None, stock_tag=None):
    """Extra candidates routed by query/genre. Cheap: only calls relevant providers."""
    ql = q.lower()
    out = coverr(q, tag=stock_tag)
    if not out:
        out += mixkit(q, tag=stock_tag)
    if any(w in ql for w in SPACE_WORDS):
        out += nasa(q)
    if genre == "dmt" or any(w in ql for w in VINTAGE_WORDS):
        out += prelinger(q.replace("psychedelic", "abstract"))
    out += pixabay(q)
    if len(out) < 2:
        out += wikimedia(q, limit=3)
    return out


def fetch_by_id(vid):
    """Resolve a namespaced id back to a candidate (for pinned re-fetches)."""
    ns, _, raw = str(vid).partition(":")
    if ns == "mixkit":
        return {
            "id": vid,
            "source": "mixkit",
            "image": (
                f"https://assets.mixkit.co/videos/{raw}/"
                f"{raw}-thumb-360-0.jpg"
            ),
            "video_files": [
                {
                    "link": f"https://assets.mixkit.co/videos/{raw}/{raw}-720.mp4",
                    "width": 1280,
                    "height": 720,
                },
                {
                    "link": f"https://assets.mixkit.co/videos/{raw}/{raw}-360.mp4",
                    "width": 640,
                    "height": 360,
                },
            ],
        }
    if ns == "coverr":
        return {
            "id": vid,
            "source": "coverr",
            "image": (
                f"https://cdn.coverr.co/videos/{raw}/thumbnail?width=640"
            ),
            "video_files": [
                {
                    "link": f"https://cdn.coverr.co/videos/{raw}/1080p.mp4",
                    "width": 1920,
                    "height": 1080,
                },
                {
                    "link": f"https://cdn.coverr.co/videos/{raw}/720p.mp4",
                    "width": 1280,
                    "height": 720,
                },
                {
                    "link": f"https://cdn.coverr.co/videos/{raw}/360p.mp4",
                    "width": 640,
                    "height": 360,
                },
            ],
        }
    if ns == "nasa":
        files = _get(f"https://images-assets.nasa.gov/video/{urllib.parse.quote(raw)}/collection.json")
        mp4s = [urllib.parse.quote(u.replace("http://", "https://"), safe=":/~")
                for u in files if u.endswith(".mp4")]
        pick = next((u for u in mp4s if "~large" in u), mp4s[0])
        return {"id": vid, "video_files": [{"link": pick, "width": 1920, "height": 1080}]}
    if ns == "ia":
        md = _get(f"https://archive.org/metadata/{raw}")
        f0 = sorted((f for f in md["files"] if f["name"].endswith(".mp4")),
                    key=lambda f: -int(f.get("size", 0) or 0))[0]
        return {"id": vid, "video_files": [{"link": f"https://archive.org/download/{raw}/"
                                                    f"{urllib.parse.quote(f0['name'])}",
                                            "width": 1280, "height": 720}]}
    if ns == "wm":
        d = _get(f"https://commons.wikimedia.org/w/api.php?action=query&pageids={raw}"
                 "&prop=videoinfo&viprop=url|size&format=json")
        vi = list(d["query"]["pages"].values())[0]["videoinfo"][0]
        return {"id": vid, "video_files": [{"link": vi["url"], "width": vi.get("width", 1280),
                                            "height": vi.get("height", 720)}]}
    raise ValueError(f"unknown source for id {vid}")
