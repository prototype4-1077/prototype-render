"""Three-way merge for the shared learning memory.

Concurrent renders both mutate pipeline/memory.json. The old push-retry reset to
origin/main and copied its own snapshot back on top, silently erasing whatever
the other render had just learned. This merges instead.

    python3 pipeline/merge_memory.py BASE OURS THEIRS OUT

BASE   = memory.json as checked out before this render mutated it
OURS   = this render's version
THEIRS = the version currently on origin/main
"""
from __future__ import annotations
import json, sys
from pathlib import Path


def _key(item):
    """Stable identity for dedupe: prefer an id-ish field, else full content."""
    if isinstance(item, dict):
        for field in ("id", "video_id", "clip_id", "slug", "query"):
            if field in item:
                return (field, json.dumps(item[field], sort_keys=True))
    return ("_raw", json.dumps(item, sort_keys=True))


def merge_list(base, ours, theirs):
    """Order-preserving union. Anything either side added is kept; anything a
    side explicitly removed relative to base stays removed only if the other
    side did not re-add it."""
    base = base or []; ours = ours or []; theirs = theirs or []
    base_keys = {_key(x) for x in base}
    ours_keys = {_key(x) for x in ours}
    theirs_keys = {_key(x) for x in theirs}
    removed = {k for k in base_keys if k not in ours_keys and k not in theirs_keys}
    out, seen = [], set()
    for item in list(base) + list(theirs) + list(ours):
        k = _key(item)
        if k in seen or k in removed:
            continue
        seen.add(k); out.append(item)
    return out


def merge_dict(base, ours, theirs):
    """Per-key three-way: a side that changed a key wins; ours breaks ties."""
    base = base or {}; ours = ours or {}; theirs = theirs or {}
    out = dict(theirs)
    for key in set(base) | set(ours) | set(theirs):
        b, o, t = base.get(key), ours.get(key), theirs.get(key)
        if isinstance(b, dict) or isinstance(o, dict) or isinstance(t, dict):
            out[key] = merge_dict(b, o, t)
        elif isinstance(b, list) or isinstance(o, list) or isinstance(t, list):
            out[key] = merge_list(b, o, t)
        elif key in ours and o != b:
            out[key] = o          # we changed it
        elif key in theirs and t != b:
            out[key] = t          # they changed it
        elif key in ours or key in theirs:
            out[key] = o if key in ours else t
    # a key both sides deleted stays deleted
    for key in list(out):
        if key in base and key not in ours and key not in theirs:
            del out[key]
    return out


def merge(base: dict, ours: dict, theirs: dict) -> dict:
    return merge_dict(base, ours, theirs)


def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    if len(argv) < 4:
        print(__doc__)
        return 2
    base, ours, theirs, out = argv[:4]
    merged = merge(_load(base), _load(ours), _load(theirs))
    Path(out).write_text(json.dumps(merged, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    counts = {k: len(v) for k, v in merged.items() if isinstance(v, (list, dict))}
    print("merged memory:", json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
