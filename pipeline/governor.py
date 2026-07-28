"""Public API for the video Pipeline Governor.

Implementation is split into small modules so process supervision, incident
analysis, shared policy utilities, and observability remain independently
testable.
"""
from governor_observed import PipelineGovernor
from governor_types import (
    MEDIA_SUFFIXES,
    POLICIES,
    SCHEMA_VERSION,
    PolicyDecision,
    StageSpec,
    artifact_signature,
    atomic_write_json,
    classify_command,
    classify_failure,
    failure_fingerprint,
    load_json,
    normalize_error,
    percentile,
    redact_secrets,
    retry_budget,
    signatures_differ,
    utc_now,
)

__all__ = [
    "MEDIA_SUFFIXES",
    "POLICIES",
    "SCHEMA_VERSION",
    "PipelineGovernor",
    "PolicyDecision",
    "StageSpec",
    "artifact_signature",
    "atomic_write_json",
    "classify_command",
    "classify_failure",
    "failure_fingerprint",
    "load_json",
    "normalize_error",
    "percentile",
    "redact_secrets",
    "retry_budget",
    "signatures_differ",
    "utc_now",
]
