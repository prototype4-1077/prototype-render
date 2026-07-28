"""Durable operational memory for render incidents, fixes, and prevention rules.

The Governor is a flight recorder. This module turns its evidence into a repair
manual by connecting stable incidents to curated solutions and future preflight
rules. Occurrences are immutable one-file records so concurrent renders do not
fight over one append-only file. ``rebuild-index`` materializes compact views.

Commands:
    python3 pipeline/operational_memory.py record-preflight build/<slug>
    python3 pipeline/operational_memory.py record-run build/<slug>
    python3 pipeline/operational_memory.py rebuild-index
    python3 pipeline/operational_memory.py show [fingerprint-or-code]
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from governor import failure_fingerprint, normalize_error

SCHEMA_VERSION = 1
HERE = Path(__file__).resolve().parent
DEFAULT_STORE = HERE / "operational_memory"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _safe_slug(value: Any) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "unknown")).strip("-.")
    return cleaned or "unknown"


def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def load_catalog(store: str | os.PathLike[str] = DEFAULT_STORE) -> dict[str, Any]:
    root = Path(store)
    raw = _load_json(root / "solutions.json", {"solutions": []})
    solutions = raw.get("solutions") if isinstance(raw, dict) else []
    return {
        str(item.get("id")): item
        for item in (solutions or [])
        if isinstance(item, dict) and item.get("id")
    }


def load_rules(store: str | os.PathLike[str] = DEFAULT_STORE) -> dict[str, Any]:
    root = Path(store)
    raw = _load_json(root / "prevention_rules.json", {"rules": []})
    rules = raw.get("rules") if isinstance(raw, dict) else []
    return {
        str(item.get("id")): item
        for item in (rules or [])
        if isinstance(item, dict) and item.get("id")
    }


def match_solutions(
    *,
    code: str | None = None,
    fingerprint: str | None = None,
    message: str | None = None,
    store: str | os.PathLike[str] = DEFAULT_STORE,
) -> list[str]:
    """Return curated solution IDs whose match contract covers this incident."""
    normalized = normalize_error(message or "", limit=1200)
    found: list[str] = []
    for solution_id, item in load_catalog(store).items():
        match = item.get("match") or {}
        codes = {str(value) for value in (match.get("codes") or [])}
        fingerprints = {str(value) for value in (match.get("fingerprints") or [])}
        contains_any = [normalize_error(str(value), limit=300) for value in (match.get("contains_any") or [])]
        contains_all = [normalize_error(str(value), limit=300) for value in (match.get("contains_all") or [])]
        code_match = bool(code and code in codes)
        fingerprint_match = bool(fingerprint and fingerprint in fingerprints)
        any_match = bool(contains_any and any(fragment in normalized for fragment in contains_any))
        all_match = bool(contains_all and all(fragment in normalized for fragment in contains_all))
        if code_match or fingerprint_match or any_match or all_match:
            found.append(solution_id)
    return sorted(set(found))


def _occurrence_filename(record: Mapping[str, Any]) -> str:
    stable = "|".join(
        str(record.get(key) or "")
        for key in (
            "phase", "github_run_id", "slug", "status", "code", "fingerprint", "stage"
        )
    )
    digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]
    run = _safe_slug(record.get("github_run_id") or record.get("run_id") or "manual")
    slug = _safe_slug(record.get("slug"))
    phase = _safe_slug(record.get("phase"))
    return f"{phase}-{run}-{slug}-{digest}.json"


def write_occurrence(
    record: Mapping[str, Any],
    *,
    store: str | os.PathLike[str] = DEFAULT_STORE,
) -> Path:
    """Persist one immutable/idempotent occurrence and return its path."""
    root = Path(store)
    payload = dict(record)
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("recorded_at", utc_now())
    payload.setdefault("matched_solution_ids", match_solutions(
        code=str(payload.get("code") or "") or None,
        fingerprint=str(payload.get("fingerprint") or "") or None,
        message=str(payload.get("normalized_error") or payload.get("message") or ""),
        store=root,
    ))
    path = root / "occurrences" / _occurrence_filename(payload)
    if path.exists():
        return path
    _atomic_json(path, payload)
    return path


def _read_occurrences(store: str | os.PathLike[str] = DEFAULT_STORE) -> list[dict[str, Any]]:
    root = Path(store)
    rows: list[dict[str, Any]] = []
    for path in sorted((root / "occurrences").glob("*.json")):
        payload = _load_json(path, None)
        candidates = []
        if isinstance(payload, dict) and isinstance(payload.get("occurrences"), list):
            candidates = [item for item in payload["occurrences"] if isinstance(item, dict)]
        elif isinstance(payload, dict):
            candidates = [payload]
        for item in candidates:
            item = dict(item)
            item["_path"] = str(path.relative_to(root))
            rows.append(item)
    return rows


def _incident_key(row: Mapping[str, Any]) -> str:
    code = str(row.get("code") or "").strip()
    if code and code not in {"render_success", "preflight_pass"}:
        return f"code:{code}"
    fingerprint = str(row.get("fingerprint") or "").strip()
    if fingerprint:
        return f"fingerprint:{fingerprint}"
    return f"status:{row.get('status') or 'unknown'}"


def _iso_sort(value: Any) -> str:
    return str(value or "")


def rebuild_index(
    *,
    store: str | os.PathLike[str] = DEFAULT_STORE,
) -> dict[str, Any]:
    """Materialize incident and solution evidence views from immutable records."""
    root = Path(store)
    rows = _read_occurrences(root)
    solutions = load_catalog(root)

    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _incident_key(row)
        item = grouped.setdefault(key, {
            "incident_key": key,
            "code": row.get("code"),
            "fingerprints": [],
            "stages": [],
            "statuses": defaultdict(int),
            "phases": defaultdict(int),
            "slugs": [],
            "first_seen": row.get("recorded_at"),
            "last_seen": row.get("recorded_at"),
            "occurrence_count": 0,
            "normalized_error": row.get("normalized_error") or row.get("message"),
            "matched_solution_ids": [],
            "latest_record": None,
        })
        item["occurrence_count"] += 1
        item["statuses"][str(row.get("status") or "unknown")] += 1
        item["phases"][str(row.get("phase") or "unknown")] += 1
        for field, target in (("fingerprint", "fingerprints"), ("stage", "stages"), ("slug", "slugs")):
            value = row.get(field)
            if value and value not in item[target]:
                item[target].append(value)
        for solution_id in row.get("matched_solution_ids") or []:
            if solution_id not in item["matched_solution_ids"]:
                item["matched_solution_ids"].append(solution_id)
        when = row.get("recorded_at")
        if _iso_sort(when) < _iso_sort(item.get("first_seen")):
            item["first_seen"] = when
        if _iso_sort(when) >= _iso_sort(item.get("last_seen")):
            item["last_seen"] = when
            item["latest_record"] = row.get("_path")
            item["normalized_error"] = row.get("normalized_error") or row.get("message")

    incidents: list[dict[str, Any]] = []
    for item in grouped.values():
        item["statuses"] = dict(sorted(item["statuses"].items()))
        item["phases"] = dict(sorted(item["phases"].items()))
        item["fingerprints"] = sorted(item["fingerprints"])
        item["stages"] = sorted(item["stages"])
        item["slugs"] = sorted(item["slugs"])
        item["matched_solution_ids"] = sorted(item["matched_solution_ids"])
        incidents.append(item)
    incidents.sort(key=lambda item: (-int(item["occurrence_count"]), str(item["incident_key"])))

    evidence: dict[str, dict[str, Any]] = {}
    for solution_id, solution in solutions.items():
        fixed_at = str(solution.get("fixed_at") or "")
        related = [row for row in rows if solution_id in (row.get("matched_solution_ids") or [])]
        after_fix = [row for row in related if not fixed_at or _iso_sort(row.get("recorded_at")) >= fixed_at]
        success = [row for row in after_fix if str(row.get("status")) in {"passed", "done", "success"}]
        recurrence = [row for row in after_fix if str(row.get("status")) in {"blocked", "failed", "quality_failed", "error"}]
        evidence[solution_id] = {
            "solution_id": solution_id,
            "catalog_status": solution.get("status"),
            "successful_verifications": len(success),
            "recurrences_after_fix": len(recurrence),
            "last_verified_at": max((_iso_sort(row.get("recorded_at")) for row in success), default=None),
            "last_recurrence_at": max((_iso_sort(row.get("recorded_at")) for row in recurrence), default=None),
            "affected_slugs": sorted({str(row.get("slug")) for row in related if row.get("slug")}),
            "verification_requirement": solution.get("verification_requirement"),
        }

    open_failure_count = 0
    failure_occurrence_count = 0
    for item in incidents:
        failures = (
            int(item["statuses"].get("failed", 0))
            + int(item["statuses"].get("blocked", 0))
            + int(item["statuses"].get("quality_failed", 0))
            + int(item["statuses"].get("error", 0))
        )
        failure_occurrence_count += failures
        resolved_by = []
        for solution_id in item.get("matched_solution_ids") or []:
            proof = evidence.get(solution_id) or {}
            verified_at = str(proof.get("last_verified_at") or "")
            if verified_at and verified_at >= str(item.get("last_seen") or ""):
                resolved_by.append(solution_id)
        if failures == 0:
            item["current_state"] = "informational"
        elif resolved_by:
            item["current_state"] = "resolved"
            item["resolved_by_solution_ids"] = sorted(resolved_by)
        else:
            item["current_state"] = "open"
            open_failure_count += 1

    incident_payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "occurrence_count": len(rows),
        "incidents": incidents,
    }
    index_payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "occurrence_count": len(rows),
        "incident_count": len(incidents),
        "solution_count": len(solutions),
        "failure_occurrence_count": failure_occurrence_count,
        "open_failure_count": open_failure_count,
        "unresolved_solution_count": sum(
            1 for item in evidence.values()
            if item.get("catalog_status") != "verified" and not item.get("successful_verifications")
        ),
        "solution_evidence": evidence,
        "top_incidents": incidents[:20],
    }
    _atomic_json(root / "incidents.json", incident_payload)
    _atomic_json(root / "index.json", index_payload)
    return index_payload


def _status_from_files(build_dir: Path) -> tuple[str, dict[str, Any], dict[str, Any]]:
    render_status = _load_json(build_dir / "render-status.json", {})
    summary = _load_json(build_dir / "governor-summary.json", {})
    status = str(summary.get("status") or render_status.get("state") or "unknown")
    return status, render_status, summary


def record_preflight(
    build_dir: str | os.PathLike[str],
    *,
    github_run_id: str | None = None,
    commit_sha: str | None = None,
    store: str | os.PathLike[str] = DEFAULT_STORE,
) -> list[Path]:
    build = Path(build_dir)
    report = _load_json(build / "preflight-report.json", {})
    slug = str(report.get("slug") or build.name)
    passed = bool(report.get("passed"))
    common = {
        "phase": "preflight",
        "github_run_id": github_run_id or os.environ.get("GITHUB_RUN_ID"),
        "commit_sha": commit_sha or os.environ.get("GITHUB_SHA"),
        "slug": slug,
        "preflight_report": str(build / "preflight-report.json"),
        "narration_fingerprint": report.get("narration_fingerprint"),
        "applied_solution_ids": report.get("applied_solution_ids") or [],
    }
    paths: list[Path] = []
    blockers = report.get("blockers") or []
    if passed:
        paths.append(write_occurrence({
            **common,
            "status": "passed",
            "code": "preflight_pass",
            "stage": "preflight",
            "message": "Mandatory render readiness preflight passed.",
            "matched_solution_ids": sorted(set(
                (report.get("matched_solution_ids") or [])
                + (report.get("applied_solution_ids") or [])
            )),
        }, store=store))
        return paths
    for blocker in blockers or [{"code": "preflight_failed", "message": "Preflight failed"}]:
        code = str(blocker.get("code") or "preflight_failed")
        message = str(blocker.get("message") or blocker)
        fingerprint = str(blocker.get("fingerprint") or failure_fingerprint("preflight", "failure", message))
        paths.append(write_occurrence({
            **common,
            "status": "blocked",
            "code": code,
            "stage": str(blocker.get("stage") or "preflight"),
            "message": message,
            "normalized_error": normalize_error(message),
            "fingerprint": fingerprint,
            "matched_solution_ids": sorted(set(
                (blocker.get("matched_solution_ids") or [])
                + match_solutions(code=code, fingerprint=fingerprint, message=message, store=store)
            )),
        }, store=store))
    return paths


def record_run(
    build_dir: str | os.PathLike[str],
    *,
    github_run_id: str | None = None,
    commit_sha: str | None = None,
    store: str | os.PathLike[str] = DEFAULT_STORE,
) -> list[Path]:
    build = Path(build_dir)
    status, render_status, summary = _status_from_files(build)
    slug = str(summary.get("slug") or render_status.get("slug") or build.name)
    run_id = github_run_id or summary.get("github_run_id") or os.environ.get("GITHUB_RUN_ID")
    preflight = _load_json(build / "preflight-report.json", {})
    inherited_solutions = sorted(set(
        (preflight.get("matched_solution_ids") or [])
        + (preflight.get("applied_solution_ids") or [])
    ))
    common = {
        "phase": "render",
        "github_run_id": run_id,
        "run_id": summary.get("run_id") or render_status.get("run_id"),
        "commit_sha": commit_sha or os.environ.get("GITHUB_SHA"),
        "slug": slug,
        "narration_fingerprint": preflight.get("narration_fingerprint"),
        "render_status": status,
    }
    done = status in {"done", "success", "passed"}
    if done:
        quality = summary.get("quality") or _load_json(build / "quality_report.json", {})
        return [write_occurrence({
            **common,
            "status": "done",
            "code": "render_success",
            "stage": "render",
            "message": str(summary.get("last_message") or render_status.get("last_message") or "Render completed"),
            "quality_passed": bool(quality.get("passed", True)),
            "matched_solution_ids": inherited_solutions,
        }, store=store)]

    incidents = summary.get("incidents") or []
    if not incidents:
        message = str(summary.get("last_message") or render_status.get("last_message") or f"Render ended with status {status}")
        fingerprint = failure_fingerprint("render", "failure", message)
        incidents = [{
            "stage": "render",
            "failure_class": "unknown",
            "fingerprint": fingerprint,
            "normalized_error": normalize_error(message),
            "count": 1,
        }]
    paths: list[Path] = []
    for incident in incidents:
        message = str(incident.get("normalized_error") or summary.get("last_message") or render_status.get("last_message") or status)
        stage = str(incident.get("stage") or "render")
        fingerprint = str(incident.get("fingerprint") or failure_fingerprint(stage, "failure", message))
        code = str(incident.get("code") or f"{stage}_failure")
        matched = sorted(set(
            inherited_solutions
            + match_solutions(code=code, fingerprint=fingerprint, message=message, store=store)
        ))
        paths.append(write_occurrence({
            **common,
            "status": "failed" if status not in {"quality_failed"} else "quality_failed",
            "code": code,
            "stage": stage,
            "failure_class": incident.get("failure_class"),
            "fingerprint": fingerprint,
            "message": message,
            "normalized_error": normalize_error(message),
            "reported_count": int(incident.get("count") or 1),
            "matched_solution_ids": matched,
        }, store=store))
    return paths


def _print_summary(store: Path, needle: str | None = None) -> None:
    index = _load_json(store / "index.json", {})
    incidents = _load_json(store / "incidents.json", {}).get("incidents", [])
    if needle:
        lowered = needle.lower()
        incidents = [item for item in incidents if lowered in json.dumps(item).lower()]
    print(json.dumps({
        "index": index,
        "incidents": incidents[:20],
        "solutions": list(load_catalog(store).values()),
    }, indent=2, ensure_ascii=False, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default=str(DEFAULT_STORE))
    sub = parser.add_subparsers(dest="command", required=True)

    pre = sub.add_parser("record-preflight")
    pre.add_argument("build_dir")
    pre.add_argument("--github-run-id")
    pre.add_argument("--commit-sha")

    run = sub.add_parser("record-run")
    run.add_argument("build_dir")
    run.add_argument("--github-run-id")
    run.add_argument("--commit-sha")

    sub.add_parser("rebuild-index")
    show = sub.add_parser("show")
    show.add_argument("needle", nargs="?")

    args = parser.parse_args(argv)
    store = Path(args.store)
    if args.command == "record-preflight":
        paths = record_preflight(
            args.build_dir,
            github_run_id=args.github_run_id,
            commit_sha=args.commit_sha,
            store=store,
        )
        print("\n".join(str(path) for path in paths))
        return 0
    if args.command == "record-run":
        paths = record_run(
            args.build_dir,
            github_run_id=args.github_run_id,
            commit_sha=args.commit_sha,
            store=store,
        )
        print("\n".join(str(path) for path in paths))
        return 0
    if args.command == "rebuild-index":
        print(json.dumps(rebuild_index(store=store), indent=2, sort_keys=True))
        return 0
    _print_summary(store, args.needle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
