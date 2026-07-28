# System Diagnostic

Generated: 2026-07-27T18:13:26+00:00

Findings: 13 — priorities {"high": 2, "low": 2, "medium": 9}

## Action queue

### [HIGH] Open Incident
- Area: `operations`
- Code: `operational:open_incident:code:visual_symbol_plan`
- Evidence: "2 occurrence(s)"
- Action: Resolve the root cause and attach a later verification occurrence before promotion.

### [HIGH] Evidence Coverage
- Area: `visual_memory`
- Code: `visual:evidence_coverage:general`
- Evidence: "Only 43 of 2472 scene records have a human decision (1.7%)."
- Action: Do not convert automated risk frequency into house rules. Review the highest-risk asset-backed queue first.

### [MEDIUM] The evolution queue is flooded with taxonomy gaps
- Area: `concept_engine`
- Code: `evolution_taxonomy_gap_flood`
- Evidence: {"count": 59, "examples": ["a-chair-not-a-throne", "awake-inside-the-dream", "belief-is-gravity", "can-you-fly", "can-you-fly-v3", "deepest-sleep", "dmt-customs", "dmt-loading-screen", "dmt-other-side-of-the-door", "dmt-the-understudy", "futures-fingerprints", "how-you-doing", "inner-search", "june-oxley-folks-aint-roadblocks-tier1", "june-oxley-left-the-vehicle"]}
- Action: Separate legacy packages missing metadata from genuinely novel concepts before treating every uncataloged slug as a map failure.

### [MEDIUM] Stored feedback has been organized into provisional rule candidates
- Area: `learning`
- Code: `feedback_rule_candidates_ready`
- Evidence: {"candidate_count": 14, "top_candidates": [{"evidence_count": 13, "id": "effects_still_preference", "title": "Use a strong still with effects when stock cannot explain the beat"}, {"evidence_count": 6, "id": "caption_restraint", "title": "Do not print performance tags or dense paragraph captions"}, {"evidence_count": 5, "id": "character_lip_sync", "title": "Visible speaking character requires mouth movement"}, {"evidence_count": 5, "id": "dmt_motion_language", "title": "DMT videos benefit from psychedelic moving graphics in moderation"}, {"evidence_count": 5, "id": "stock_first_preference", "title": "Prefer genuine moving stock when a direct match exists"}, {"evidence_count": 5, "id": "visual_semantic_match", "title": "Visual must clearly represent the spoken concept"}, {"evidence_count": 3, "id": "title_safe_zone", "title": "Titles must remain readable inside platform crop zones"}, {"evidence_count": 2, "id": "deep_parallax", "title": "Concept backgrounds should use strong layered depth"}, {"evidence_count": 2, "id": "literal_action_accuracy", "title": "Literal actions must visibly perform the stated action"}, {"evidence_count": 1, "id": "cartoon_animation_definition", "title": "Animated requests mean coherent cartoon animation"}], "unique_commented_evidence": 124}
- Action: Review candidate scope and counterexamples. Promote only candidates with a human decision and a regression test.

### [MEDIUM] Too few reviewable videos have exported human feedback
- Area: `learning`
- Code: `human_feedback_coverage_low`
- Evidence: {"coverage": 0.1, "feedback_count": 2, "feedback_slugs": ["belief-is-gravity", "the-edge-of-you-is-negotiable"], "reviewable_count": 20, "reviewable_slugs": ["a-chair-not-a-throne", "belief-is-gravity", "beliefs-are-software-updates", "dispatch-path-selftest", "june-oxley-left-the-vehicle", "the-adjacent-mind", "the-blueprint-recognizes-the-building", "the-edge-of-you-is-negotiable", "the-emotion-scam-tier1", "the-infinite-library", "the-mercy-of-the-filter", "the-reality-machine-dmt-v3", "the-room-has-more-than-one-window", "the-universe-keeps-its-options-open", "the-witness-without-a-face", "tomorrow-uses-old-footage", "who-wrote-the-menu", "wonder-is-a-glitch", "your-emergency-contact", "your-inner-bodyguard"]}
- Action: Review the highest-value completed videos first. Keep automated risk tags as screening evidence until James supplies a decision.

### [MEDIUM] Some operational solutions still need verification
- Area: `operations`
- Code: `provisional_operational_solutions`
- Evidence: ["sol-animation-contract-preflight-v1", "sol-hero-readiness-v1"]
- Action: Satisfy each stated verification requirement before marking it verified; do not promote by elapsed time alone.

### [MEDIUM] Youtube queue contains already-published videos
- Area: `publishing`
- Code: `youtube_published_still_queued`
- Evidence: ["a-chair-not-a-throne", "beliefs-are-software-updates", "beliefs-are-software-updates-short", "the-adjacent-mind", "the-edge-of-you-is-negotiable", "the-forecast-in-your-chest", "the-infinite-library", "the-museum-that-repaints-itself", "the-person-you-replaced", "the-press-secretary-in-your-skull", "the-reality-machine-dmt-v3", "the-room-has-more-than-one-window", "tomorrow-uses-old-footage", "who-wrote-the-menu", "wonder-is-a-glitch", "you-are-a-flame-wearing-a-name-tag", "your-emergency-contact", "your-inner-bodyguard"]
- Action: Keep the metadata queue if useful, but rely on durable receipt checks and make duplicate posting require an explicit force flag.

### [MEDIUM] Quality warning repeats: long_black_interval
- Area: `quality`
- Code: `repeated_quality_warning:long_black_interval`
- Evidence: {"current_build_reports": 2}
- Action: Run a targeted encoding or assembly challenger and require unchanged visual/audio quality before adoption.

### [MEDIUM] Quality warning repeats: low_bitrate
- Area: `quality`
- Code: `repeated_quality_warning:low_bitrate`
- Evidence: {"current_build_reports": 6}
- Action: Run a targeted encoding or assembly challenger and require unchanged visual/audio quality before adoption.

### [MEDIUM] Asset Coverage
- Area: `visual_memory`
- Code: `visual:asset_coverage:general`
- Evidence: "Only 127 of 2472 records retain a reviewable asset (5.1%)."
- Action: Persist representative frames or durable release references for completed scenes so historical feedback remains inspectable.

### [MEDIUM] Low Approval Cohort
- Area: `visual_memory`
- Code: `visual:low_approval_cohort:symbol_family:cartography`
- Evidence: "1/3 approved (33%)"
- Action: Inspect the cohort before changing global routing; topic and scene difficulty may be confounders.

### [LOW] The WhisperX challenger has no materialized benchmark ledger
- Area: `alignment`
- Code: `whisperx_ledger_absent`
- Evidence: "pipeline/whisperx-benchmark-ledger.json is absent"
- Action: Run shadow alignment on eligible successful videos and add the first manually reviewed timing references before considering promotion.

### [LOW] Permanent stock exclusion now has a measured supply signal
- Area: `asset_selection`
- Code: `stock_supply:no_current_starvation_signal`
- Evidence: {"exclusions": {"banned_ids": 102, "used_ids": 1021}, "fallback_rate": 0.0466, "low_supply_rate": 0.0254, "measurement_boundary": "Candidate decisions reflect narrative-fidelity reranking after search. This report cannot reconstruct every raw API result or prove that exclusions caused a missing candidate.", "reports_analyzed": 13, "scenes_analyzed": 236, "state": "no_current_starvation_signal"}
- Action: Keep permanent exclusion unchanged; continue monitoring candidate supply and fallback rate.

## Authority boundary

This diagnostic may propose or apply deterministic infrastructure safeguards. It cannot rewrite narration, change science or political meaning, alter James's approved visual intent, publish, or promote experimental systems without the relevant approval gate.
