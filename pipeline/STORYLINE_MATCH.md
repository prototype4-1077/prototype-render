# Storyline-Match Policy

The pipeline treats visual relevance as a hard editorial requirement, not a mood suggestion.

## Standing rule

A clip must represent the action, object, relationship, or mechanism spoken in the current beat. A beautiful shot, a vaguely related noun, or a matching color grade does not compensate for a missing storyline connection.

For the first 72% of a video, scenes marked as literal anchors, mechanisms, or recursions receive a direct-match gate. Candidate titles, descriptions, and provider URL slugs are checked against the scene keywords. Contexts previously rejected by an approved edit are blocked for similar queries.

When stock footage cannot depict the beat directly, `storyline_footage.py` renders a deterministic literal storyboard rather than falling back to generic atmospheric footage. These storyboards animate labels, counters, routes, focus boxes, evidence boards, settings, scales, and related visual mechanisms.

## Approved precedent

`trained-not-to-look` / **Reality Was Never Hidden** established the policy. The approved revision kept exact-match documentary sequences and the stronger final act, while replacing unrelated early-to-middle stock footage with literal animated metaphors. Its approval and rejected clip/query contexts are stored in `editorial_memory.json`.

## Audit output

Each build writes `narrative_fidelity_report.json`, recording whether every processed scene used stock or a literal storyboard, the candidate anchor coverage, and the reason for any fallback.
