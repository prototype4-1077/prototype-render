"""Materialize operational incidents, solution evidence, warnings, and actions.

This analyzer is intentionally stricter than the compatibility indexer:
- occurrence multiplicity honors ``reported_count``;
- a successful run verifies only ``verified_solution_ids``;
- a failed run regresses only ``regressed_solution_ids`` or exact catalog matches;
- warnings and telemetry advisories become an action queue without being treated as failures;
- current state follows event order, while lifetime recurrence counts remain visible.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import os
from pathlib import Path
from typing import Any, Mapping

import operational_memory

SCHEMA_VERSION = 2


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def multiplicity(row: Mapping[str, Any]) -> int:
    try:
        return max(1, int(row.get("reported_count") or 1))
    except (TypeError, ValueError):
        return 1


def relation_ids(
    row: Mapping[str, Any],
    catalog: Mapping[str, Any],
    store: str | os.PathLike[str],
) -> tuple[list[str], list[str]]:
    status = str(row.get("status") or "")
    verified = list(row.get("verified_solution_ids") or [])
    regressed = list(row.get("regressed_solution_ids") or [])
    if not verified and status in {"passed", "done", "success"}:
        verified = list(row.get("matched_solution_ids") or [])
    if not regressed and status in {"blocked", "failed", "quality_failed", "error"}:
        regressed = operational_memory.match_solutions(
            code=str(row.get("code") or "") or None,
            fingerprint=str(row.get("fingerprint") or "") or None,
            message=str(row.get("normalized_error") or row.get("message") or ""),
            store=store,
        )
    return sorted({item for item in verified if item in catalog}), sorted({item for item in regressed if item in catalog})


def incident_key(row: Mapping[str, Any]) -> str:
    code = str(row.get("code") or "").strip()
    if code and code not in {"render_success", "preflight_pass"}:
        return f"code:{code}"
    fingerprint = str(row.get("fingerprint") or "").strip()
    if fingerprint:
        return f"fingerprint:{fingerprint}"
    return f"status:{row.get('status') or 'unknown'}"


def build(store: str | os.PathLike[str] = operational_memory.DEFAULT_STORE) -> dict[str, Any]:
    root = Path(store)
    rows = operational_memory._read_occurrences(root)
    catalog = operational_memory.load_catalog(root)
    grouped: dict[str, dict[str, Any]] = {}
    evidence = {
        solution_id: {
            "solution_id": solution_id,
            "catalog_status": solution.get("status"),
            "successful_verifications": 0,
            "recurrences_after_fix": 0,
            "last_verified_at": None,
            "last_recurrence_at": None,
            "affected_slugs": set(),
            "verification_requirement": solution.get("verification_requirement"),
        }
        for solution_id, solution in catalog.items()
    }
    warning_counts: dict[str, int] = defaultdict(int)
    advisory_counts: dict[str, int] = defaultdict(int)
    stage_samples: dict[str, list[float]] = defaultdict(list)

    for row in rows:
        count = multiplicity(row)
        verified, regressed = relation_ids(row, catalog, root)
        key = incident_key(row)
        item = grouped.setdefault(key, {
            "incident_key": key,
            "code": row.get("code"),
            "fingerprints": set(),
            "stages": set(),
            "statuses": defaultdict(int),
            "phases": defaultdict(int),
            "slugs": set(),
            "first_seen": row.get("recorded_at"),
            "last_seen": row.get("recorded_at"),
            "occurrence_count": 0,
            "normalized_error": row.get("normalized_error") or row.get("message"),
            "verified_solution_ids": set(),
            "regressed_solution_ids": set(),
            "latest_record": row.get("_path"),
        })
        item["occurrence_count"] += count
        item["statuses"][str(row.get("status") or "unknown")] += count
        item["phases"][str(row.get("phase") or "unknown")] += count
        for field, target in (("fingerprint", "fingerprints"), ("stage", "stages"), ("slug", "slugs")):
            value = row.get(field)
            if value:
                item[target].add(str(value))
        item["verified_solution_ids"].update(verified)
        item["regressed_solution_ids"].update(regressed)
        when = str(row.get("recorded_at") or "")
        if when and (not item.get("first_seen") or when < str(item["first_seen"])):
            item["first_seen"] = when
        if when >= str(item.get("last_seen") or ""):
            item["last_seen"] = when
            item["latest_record"] = row.get("_path")
            item["normalized_error"] = row.get("normalized_error") or row.get("message")

        status = str(row.get("status") or "")
        code = str(row.get("code") or "")
        if status == "warning":
            warning_counts[code] += count
        elif status == "advisory":
            advisory_counts[code] += count

        for solution_id in verified:
            proof = evidence[solution_id]
            proof["successful_verifications"] += count
            proof["last_verified_at"] = max(str(proof.get("last_verified_at") or ""), when) or None
            if row.get("slug"):
                proof["affected_slugs"].add(str(row["slug"]))
        for solution_id in regressed:
            proof = evidence[solution_id]
            proof["recurrences_after_fix"] += count
            proof["last_recurrence_at"] = max(str(proof.get("last_recurrence_at") or ""), when) or None
            if row.get("slug"):
                proof["affected_slugs"].add(str(row["slug"]))

        for source in (row.get("stage_metrics") or {}, row.get("telemetry_stage_metrics") or {}):
            if not isinstance(source, dict):
                continue
            for stage, metrics in source.items():
                if not isinstance(metrics, dict):
                    continue
                value = metrics.get("p95_success_s") or metrics.get("p95_duration_s") or metrics.get("total_duration_s")
                try:
                    if value is not None and float(value) >= 0:
                        stage_samples[str(stage)].append(float(value))
                except (TypeError, ValueError):
                    pass

    for proof in evidence.values():
        proof["affected_slugs"] = sorted(proof["affected_slugs"])
        last_verified = str(proof.get("last_verified_at") or "")
        last_recurrence = str(proof.get("last_recurrence_at") or "")
        proof["evidence_state"] = (
            "verified" if last_verified and last_verified >= last_recurrence else
            "regressed" if last_recurrence else
            "awaiting_evidence"
        )

    incidents: list[dict[str, Any]] = []
    open_failure_count = 0
    failure_occurrence_count = 0
    for item in grouped.values():
        for field in ("fingerprints", "stages", "slugs", "verified_solution_ids", "regressed_solution_ids"):
            item[field] = sorted(item[field])
        item["statuses"] = dict(sorted(item["statuses"].items()))
        item["phases"] = dict(sorted(item["phases"].items()))
        failures = sum(int(item["statuses"].get(name, 0)) for name in ("failed", "blocked", "quality_failed", "error"))
        failure_occurrence_count += failures
        candidates = sorted(set(item["verified_solution_ids"]) | set(item["regressed_solution_ids"]))
        resolved = []
        for solution_id in candidates:
            proof = evidence.get(solution_id) or {}
            if (
                proof.get("evidence_state") == "verified"
                and str(proof.get("last_verified_at") or "") >= str(item.get("last_seen") or "")
            ):
                resolved.append(solution_id)
        if failures == 0:
            item["current_state"] = "informational"
        elif resolved:
            item["current_state"] = "resolved"
            item["resolved_by_solution_ids"] = resolved
        else:
            item["current_state"] = "open"
            open_failure_count += 1
        incidents.append(item)
    incidents.sort(key=lambda item: (-int(item["occurrence_count"]), str(item["incident_key"])))

    actions: list[dict[str, Any]] = []
    for item in incidents:
        if item.get("current_state") == "open":
            actions.append({
                "priority": "high",
                "category": "open_incident",
                "key": item["incident_key"],
                "evidence": f"{item['occurrence_count']} occurrence(s)",
                "action": "Resolve the root cause and attach a later verification occurrence before promotion.",
            })
    for code, count in sorted(warning_counts.items(), key=lambda pair: (-pair[1], pair[0])):
        actions.append({
            "priority": "medium" if count >= 2 else "low",
            "category": "quality_warning",
            "key": code,
            "evidence": f"{count} warning occurrence(s)",
            "action": "Create a targeted champion/challenger patch if the warning repeats without a quality tradeoff.",
        })
    for code, count in sorted(advisory_counts.items(), key=lambda pair: (-pair[1], pair[0])):
        actions.append({
            "priority": "medium" if count >= 2 else "low",
            "category": "telemetry_advisory",
            "key": code,
            "evidence": f"{count} advisory occurrence(s)",
            "action": "Investigate the cohort by provider, cache state, scene type, and artifact size.",
        })
    for solution_id, proof in evidence.items():
        if proof["catalog_status"] != "verified" and proof["evidence_state"] == "verified":
            actions.append({
                "priority": "medium",
                "category": "solution_promotion_candidate",
                "key": solution_id,
                "evidence": (
                    f"{proof['successful_verifications']} successful verification(s); "
                    f"latest verification follows latest recurrence"
                ),
                "action": "Review the verification requirement and promote the catalog status only if it is satisfied.",
            })

    stage_summary = {
        stage: {
            "samples": len(values),
            "mean_signal_s": round(sum(values) / len(values), 3),
            "max_signal_s": round(max(values), 3),
        }
        for stage, values in sorted(stage_samples.items()) if values
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": operational_memory.utc_now(),
        "occurrence_count": sum(multiplicity(row) for row in rows),
        "record_file_count": len(rows),
        "incident_count": len(incidents),
        "solution_count": len(catalog),
        "failure_occurrence_count": failure_occurrence_count,
        "open_failure_count": open_failure_count,
        "warning_counts": dict(sorted(warning_counts.items())),
        "advisory_counts": dict(sorted(advisory_counts.items())),
        "stage_performance_signals": stage_summary,
        "solution_evidence": evidence,
        "action_queue": actions,
        "top_incidents": incidents[:30],
    }
    atomic_json(root / "incidents.json", {
        "schema_version": SCHEMA_VERSION,
        "generated_at": payload["generated_at"],
        "occurrence_count": payload["occurrence_count"],
        "incidents": incidents,
    })
    atomic_json(root / "index.json", payload)
    atomic_json(root / "action_queue.json", {
        "schema_version": SCHEMA_VERSION,
        "generated_at": payload["generated_at"],
        "actions": actions,
    })
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default=str(operational_memory.DEFAULT_STORE))
    args = parser.parse_args(argv)
    print(json.dumps(build(args.store), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
