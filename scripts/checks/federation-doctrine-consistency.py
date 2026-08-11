#!/usr/bin/env python3
"""Verify the static federation ownership doctrine and its mandatory entrypoints.

This gate is intentionally pure stdlib and authority-negative. It validates a
static ownership allocation; it does not inspect or characterize live runtime
health and cannot activate a bridge.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_PATH: Final[str] = "policies/federation-ownership-policy-v1.json"
VERIFIER_PATH: Final[str] = "scripts/checks/federation-doctrine-consistency.py"
EXPECTED_CANDIDATE_BASE_HEAD: Final[str] = "7adf5cd2c2d4af888c27126e01094981f821c98a"
EXPECTED_MAX_PARALLEL_IMPLEMENTATION_LANES: Final[int] = 8
EMPTY_SHA256: Final[str] = "sha256:" + hashlib.sha256(b"").hexdigest()

EXPECTED_FORMAL_INVARIANTS: Final[dict[str, object]] = {
    "cross_domain_a2_allowed": False,
    "cross_domain_effect_owner": "target_native_domain_only",
    "global_a2": "FORBIDDEN",
    "global_a2_authority": None,
    "global_sovereign_controller": None,
    "global_sovereign_writer": None,
    "primary_scientific_cortex": "scientific-resource-lab",
    "shared_srl_scientific_contract_semantics_owner": "scientific-resource-lab",
    "target_wire_order_owner": "dual-contour-research-os",
}

EXPECTED_HUMAN_METAPHOR: Final[dict[str, object]] = {
    "meaning": (
        "shared scientific cognition, computation, proof, knowledge, planning "
        "and scientific provenance"
    ),
    "never_means": [
        "global authority",
        "native domain truth",
        "native domain admission",
        "permission to trade",
        "permission to execute target-specific security actions",
        "permission to deploy or mutate protected state",
        "automatic promotion of a scientific result",
    ],
    "primary_scientific_cortex": "scientific-resource-lab",
}

EXPECTED_SEMANTIC_INVARIANTS: Final[dict[str, object]] = {
    "authority_negative_implies_proposal": False,
    "c3_semantic_kinds": ["request", "intent", "proposal_envelope"],
    "d2_cross_boundary_rule": "native_sanitized_d1_metadata_projection_only",
    "d3_cross_boundary_hash_reference_identifier_or_log_allowed": False,
    "effect_request_derived_from_evidence_requires_new_c3_proposal": True,
    "evidence_semantic_kinds": [
        "scientific_result",
        "evidence",
        "validation_artifact",
    ],
    "evidence_reclassified_as_proposal": False,
    "evidence_import_requires_versioned_successor": True,
    "imported_as_c3_scope": "proposal_payloads_only",
    "receipt_semantic_kinds": ["receipt"],
    "semantic_kind_and_authority_are_independent_axes": True,
    "simultaneous_srl_spool_and_dual_wire_order_authority": False,
    "unsupported_evidence_import_state": "WAIT_UNSUPPORTED",
}

EXPECTED_TOP_LEVEL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "activates_federation",
        "canonical_writes",
        "current_state",
        "document_bindings",
        "formal_invariants",
        "grants_authority",
        "human_metaphor",
        "participants",
        "policy_id",
        "runtime_truth",
        "schema_version",
        "semantic_invariants",
        "source_bindings",
        "status",
        "transport_transition",
        "wire_semantic_boundary",
    }
)

EXPECTED_PARTICIPANTS: Final[dict[str, tuple[str, str]]] = {
    "crosslab": ("crosslab-shadow-link-v0", "PAGER_ONLY"),
    "dual": ("dual-contour-research-os", "MECHANICAL_TRANSPORT_ORDER_FABRIC"),
    "market": ("crypto-market-lab", "NATIVE_MARKET_TRUTH_AND_EFFECT_OWNER"),
    "security": (
        "security-research-os",
        "NATIVE_SECURITY_TRUTH_SAFETY_AND_EFFECT_OWNER",
    ),
    "srl": ("scientific-resource-lab", "SCIENTIFIC_REASONING_COMPUTE_FABRIC"),
}

EXPECTED_PARTICIPANT_KEYS: Final[dict[str, frozenset[str]]] = {
    "crosslab": frozenset(
        {
            "does_not_own",
            "owns",
            "registered_peer_scope",
            "repository_id",
            "role_code",
            "srl_endpoint_allowed",
        }
    ),
    "dual": frozenset(
        {
            "does_not_own",
            "owns",
            "payload_reinterpretation_allowed",
            "repository_id",
            "role_activation",
            "role_code",
        }
    ),
    "market": frozenset({"does_not_own", "owns", "repository_id", "role_code"}),
    "security": frozenset({"does_not_own", "owns", "repository_id", "role_code"}),
    "srl": frozenset({"does_not_own", "owns", "repository_id", "role_code"}),
}

EXPECTED_CURRENT_STATE: Final[dict[str, object]] = {
    "accepted_release_head": "418aa9673b814871405e92a4a1ea13290efb3fae",
    "federation_state_source": "exact_current_native_receipts_only",
    "federation_runtime_state": "NOT_CHARACTERIZED_BY_THIS_POLICY",
    "release_truth_path": ("docs/verification/srf-v3-7-mission-closeout-blocked-v2-0-0.json"),
    "release_truth_receipt_id": (
        "sha256:a1876671c4e039285e366ae047c56bde9f565e2e9d52083a4063c6cf7bf58dcd"
    ),
    "release_truth_result": "BLOCKED_EXTERNAL_AUTHORITY",
    "role_allocation_is_runtime_evidence": False,
    "target_release": "v2.0.0",
    "target_release_published": False,
}

EXPECTED_TRANSPORT_TRANSITION: Final[dict[str, str]] = {
    "active_cross_domain_wire": "NONE_PROVEN_BY_THIS_POLICY",
    "current": ("srl_internal_spool_with_inactive_proposal_only_market_security_adapters"),
    "cutover": "never_two_cross_domain_delivery_order_authorities",
    "target": "dual_wire_after_exact_native_closeout_conformance_and_cutover_receipts",
}

BOUND_DOCUMENT_PATHS: Final[tuple[str, ...]] = (
    "AGENTS.md",
    "AUTHORITY-MATRIX.md",
    "CELL-MATRIX.md",
    "CONTRACT-MATRIX.md",
    "CONTRIBUTING.md",
    "DATA-CLASSIFICATION.md",
    "GOVERNANCE.md",
    "MARKET-INTEGRATION.md",
    "README.md",
    "SECURITY-INTEGRATION.md",
    "SOLO-AGENT-RUNBOOK.md",
    "START-HERE.md",
    "SYSTEM-ATLAS.md",
    "TRADING-EXECUTION-BOUNDARY.md",
    "docs/adr/0011-federated-research-organism-ownership.md",
    "docs/architecture/README.md",
    "docs/architecture/federated-research-organism-doctrine-v1.md",
    "docs/architecture/transport.md",
    "docs/integrations/MARKET-CHILD-MISSION.md",
    "docs/integrations/MARKET-INTEGRATION.md",
    "docs/integrations/SECURITY-CHILD-MISSION.md",
    "docs/integrations/SECURITY-INTEGRATION.md",
    "docs/integrations/shared-contracts.md",
    "docs/plans/federated-research-organism-successor-plan-v1.md",
    "src/srl/contracts/schemas/v1/README.md",
)

BOUND_SOURCE_PATHS: Final[tuple[str, ...]] = (
    ".github/workflows/docs.yml",
    "Makefile",
    "automation/policy.json",
    "automation/state.schema.json",
    "configs/integrations/market-bridge.json",
    "configs/integrations/security-bridge.json",
    "scripts/docs/generate_solo_agent_docs.py",
    "scripts/docs/generate_system_docs.py",
    "src/srl/autonomy/policy.py",
    "src/srl/contracts/schema.py",
    "src/srl/contracts/schemas/v1/evidence-assessment.json",
    "src/srl/contracts/schemas/v1/federation-status.json",
    "src/srl/contracts/schemas/v1/federation-orientation-report.json",
    "src/srl/contracts/schemas/v1/lab-cell-manifest.json",
    "src/srl/contracts/schemas/v1/lab-export-packet.json",
    "src/srl/contracts/schemas/v1/lab-federation-manifest.json",
    "src/srl/contracts/schemas/v1/science-lab-run-receipt.json",
    "src/srl/contracts/schemas/v1/scientific-import-receipt.json",
    "src/srl/contracts/schemas/v1/scientific-object-envelope.json",
    "src/srl/contracts/schemas/v1/scientific-request-envelope.json",
    "src/srl/contracts/schemas/v1/scientific-result-envelope.json",
    "src/srl/contracts/schemas/v1/scientific-run-receipt.json",
    "src/srl/contracts/schemas/v1/spool-ack.json",
    "src/srl/contracts/schemas/v1/spool-message.json",
    "src/srl/contracts/schemas/v1/srf-pulse.json",
    "src/srl/contracts/schemas/v1/transformation-receipt.json",
    "src/srl/cli.py",
    "src/srl/integrations/market/bridge.py",
    "src/srl/integrations/security/bridge.py",
    "src/srl/labctl.py",
    "src/srl/transport/spool.py",
    "tests/contracts/test_srf_federation_schemas.py",
    "tests/unit/test_labctl.py",
)

INDEPENDENT_REVIEW_RECEIPT_PATH: Final[str] = (
    "docs/verification/federation-doctrine-independent-review-v1.json"
)
DOCUMENTATION_CLOSURE_RECEIPT_PATH: Final[str] = (
    "docs/verification/documentation-closure-receipt-v2.json"
)
EVIDENCE_RECEIPT_PATHS: Final[tuple[str, ...]] = (
    DOCUMENTATION_CLOSURE_RECEIPT_PATH,
    INDEPENDENT_REVIEW_RECEIPT_PATH,
)
HISTORICAL_DOCUMENTATION_RECEIPT_PATH: Final[str] = (
    "docs/verification/documentation-closure-receipt.json"
)
SYSTEM_ACCEPTANCE_RECEIPT_PATH: Final[str] = "docs/verification/system-acceptance-receipt.json"

DOCUMENTATION_REQUIRED_PATHS: Final[tuple[str, ...]] = (
    "START-HERE.md",
    "SYSTEM-ATLAS.md",
    "SOLO-AGENT-RUNBOOK.md",
    "CELL-MATRIX.md",
    "CAPABILITY-CATALOG.md",
    "CONTRACT-MATRIX.md",
    "AUTHORITY-MATRIX.md",
    "DATA-CLASSIFICATION.md",
    "FAILURE-ROUTING.md",
    "T7-OPERATIONS.md",
    "COMPUTE-NODE.md",
    "MARKET-INTEGRATION.md",
    "SECURITY-INTEGRATION.md",
    "TRADING-EXECUTION-BOUNDARY.md",
    "PACK-AUTHORING.md",
    "PACK-REVOCATION.md",
    "RECOVERY-RUNBOOK.md",
    "RELEASE-RUNBOOK.md",
)

DOCUMENTATION_GENERATED_SOURCE_PATHS: Final[tuple[str, ...]] = (
    SYSTEM_ACCEPTANCE_RECEIPT_PATH,
    DEFAULT_POLICY_PATH,
    VERIFIER_PATH,
    "scripts/checks/markdown_structure.py",
    "scripts/docs/generate_solo_agent_docs.py",
    "scripts/docs/generate_system_docs.py",
    "tests/adversarial/test_system_acceptance_failure_routes.py",
    "tests/docs/test_documentation_closure.py",
    "tests/docs/test_federation_doctrine.py",
    "tests/e2e/test_system_acceptance_receipt.py",
)

CANDIDATE_GOVERNED_PATHS: Final[tuple[str, ...]] = tuple(
    sorted(
        {
            *BOUND_DOCUMENT_PATHS,
            *BOUND_SOURCE_PATHS,
            *DOCUMENTATION_REQUIRED_PATHS,
            *DOCUMENTATION_GENERATED_SOURCE_PATHS,
            DEFAULT_POLICY_PATH,
        }
        - set(EVIDENCE_RECEIPT_PATHS)
    )
)

V37_IMMUTABLE_PATHS: Final[tuple[str, ...]] = (
    "docs/plans/scientific-reasoning-fabric-activation-master-plan-v3.7.md",
    ":(glob)docs/verification/srf-v3-7-*.json",
)

DOCUMENT_EOF_MARKERS: Final[dict[str, str]] = {
    "docs/architecture/federated-research-organism-doctrine-v1.md": (
        "<!-- FEDERATION-DOCTRINE-END -->"
    ),
    "docs/plans/federated-research-organism-successor-plan-v1.md": (
        "<!-- FEDERATION-SUCCESSOR-PLAN-END -->"
    ),
}

POLICY_DIGEST_RE: Final[re.Pattern[str]] = re.compile(r"sha256:[0-9a-f]{8}(?:-[0-9a-f]{8}){7}")

DOCTRINE_ORIENTATION_BLOCK: Final[str] = """```text
PRIMARY_SCIENTIFIC_CORTEX: SCIENTIFIC_RESOURCE_LAB
SRL_FORMAL_ROLE: SCIENTIFIC_REASONING_COMPUTE_FABRIC
TARGET_WIRE_ORDER_OWNER: DUAL_CONTOUR
TARGET_WIRE_ORDER_ROLE_STATE: TARGET_DECLARED_NOT_RUNTIME_PROVEN
SAFETY_CORTEX: SECURITY_RESEARCH_OS
MARKET_TRUTH_OWNER: CRYPTO_MARKET_LAB
SECURITY_TRUTH_OWNER: SECURITY_RESEARCH_OS
GLOBAL_SOVEREIGN_CONTROLLER: NONE
GLOBAL_SOVEREIGN_WRITER: NONE
GLOBAL_A2: FORBIDDEN
CROSS_DOMAIN_EFFECT_OWNER: TARGET_NATIVE_DOMAIN_ONLY
CROSSLAB_ROLE: PAGER_ONLY
CROSSLAB_SRL_ENDPOINT: NONE
CURRENT_SRL_RELEASE_TRUTH: BLOCKED_EXTERNAL_AUTHORITY
CURRENT_FEDERATION_RUNTIME: NOT_CHARACTERIZED
CURRENT_SRL_RUNTIME: NOT_CHARACTERIZED
CURRENT_MARKET_RUNTIME: NOT_CHARACTERIZED
CURRENT_SECURITY_RUNTIME: NOT_CHARACTERIZED
CURRENT_DUAL_RUNTIME: NOT_CHARACTERIZED
FEDERATION_RUNTIME_STATE_SOURCE: EXACT_CURRENT_NATIVE_RECEIPTS_ONLY
DECLARED_WRITE_SCOPE: <caller-declared scope or NONE>
DECLARED_WRITE_SCOPE_GRANTS_AUTHORITY: FALSE
```"""

AGENT_ORIENTATION_BLOCK: Final[str] = """```text
PRIMARY_SCIENTIFIC_CORTEX: SCIENTIFIC_RESOURCE_LAB
SRL_FORMAL_ROLE: SCIENTIFIC_REASONING_COMPUTE_FABRIC
TARGET_WIRE_ORDER_OWNER: DUAL_CONTOUR
TARGET_WIRE_ORDER_ROLE_STATE: TARGET_DECLARED_NOT_RUNTIME_PROVEN
SAFETY_CORTEX: SECURITY_RESEARCH_OS
MARKET_TRUTH_OWNER: CRYPTO_MARKET_LAB
SECURITY_TRUTH_OWNER: SECURITY_RESEARCH_OS
GLOBAL_SOVEREIGN_CONTROLLER: NONE
GLOBAL_SOVEREIGN_WRITER: NONE
GLOBAL_A2: FORBIDDEN
CROSS_DOMAIN_EFFECT_OWNER: TARGET_NATIVE_DOMAIN_ONLY
CROSSLAB_ROLE: PAGER_ONLY
CROSSLAB_SRL_ENDPOINT: NONE
CURRENT_SRL_RELEASE_TRUTH: BLOCKED_EXTERNAL_AUTHORITY
CURRENT_FEDERATION_RUNTIME: NOT_CHARACTERIZED
CURRENT_SRL_RUNTIME: NOT_CHARACTERIZED
CURRENT_MARKET_RUNTIME: NOT_CHARACTERIZED
CURRENT_SECURITY_RUNTIME: NOT_CHARACTERIZED
CURRENT_DUAL_RUNTIME: NOT_CHARACTERIZED
FEDERATION_RUNTIME_STATE_SOURCE: EXACT_CURRENT_NATIVE_RECEIPTS_ONLY
DECLARED_WRITE_SCOPE: <caller-declared scope or NONE>
DECLARED_WRITE_SCOPE_GRANTS_AUTHORITY: FALSE
```"""

REQUIRED_DOC_MARKERS: Final[dict[str, tuple[str, ...]]] = {
    "AGENTS.md": (
        "## Mandatory Static Target Doctrine Comprehension Gate",
        "PRIMARY_SCIENTIFIC_CORTEX: SCIENTIFIC_RESOURCE_LAB",
        "TARGET_WIRE_ORDER_OWNER: DUAL_CONTOUR",
        "TARGET_WIRE_ORDER_ROLE_STATE: TARGET_DECLARED_NOT_RUNTIME_PROVEN",
        "GLOBAL_SOVEREIGN_CONTROLLER: NONE",
        "GLOBAL_SOVEREIGN_WRITER: NONE",
        "GLOBAL_A2: FORBIDDEN",
        "CROSS_DOMAIN_EFFECT_OWNER: TARGET_NATIVE_DOMAIN_ONLY",
        "CROSSLAB_SRL_ENDPOINT: NONE",
        "CURRENT_FEDERATION_RUNTIME: NOT_CHARACTERIZED",
        "DECLARED_WRITE_SCOPE_GRANTS_AUTHORITY: FALSE",
        "srlab labctl federation-orient",
        "Static role allocation never proves",
    ),
    "README.md": (
        "## Role in the federation",
        "primary scientific cortex",
        "Global A2 is forbidden.",
    ),
    "START-HERE.md": (
        "Before using a bridge or describing cross-repository ownership",
        "primary scientific cortex without granting global",
        "Dual Wire as a target role whose runtime is unproven",
    ),
    "SYSTEM-ATLAS.md": (
        "not current federation",
        "not proof that any target bridge or Dual Wire is active",
        "legacy/inactive SRL adapter; not target Dual Wire",
    ),
    "CELL-MATRIX.md": (
        "legacy/inactive SRL adapter; not target Dual Wire",
        "Market and Security adapter cells are proposal-only",
    ),
    "CONTRACT-MATRIX.md": (
        "Ownership and authority boundaries are defined by",
        "SpoolMessage/v1` and `SpoolAck/v1` are SRL-internal transport contracts",
        "not the target Dual Wire and grant no cross-domain authority",
    ),
    "AUTHORITY-MATRIX.md": (
        "SRF requests and intents remain C3 proposals",
        "Receipts retain receipt",
        "validation artifacts retain evidence semantics",
        "authority-negative and are never reclassified as C3",
    ),
    "CONTRIBUTING.md": (
        "Evidence over enthusiasm",
        "changes follow the governance-change template",
        "Rollback",
    ),
    "DATA-CLASSIFICATION.md": (
        "public digest or typed WAIT",
        "new sanitized D1",
        "raw D2 must never be relabelled D1",
        "D3 produces no",
    ),
    "GOVERNANCE.md": (
        "## Governance-change workflow",
        "Independent review receipt",
        "No self-validation",
    ),
    "MARKET-INTEGRATION.md": (
        "Recorded V3.7 evidence at its bound generation",
        "not current Market runtime truth",
        "current truth requires native bootstrap",
    ),
    "SECURITY-INTEGRATION.md": (
        "Recorded V3.7 evidence at its bound generation",
        "not current Security runtime truth",
        "current truth requires native",
    ),
    "SOLO-AGENT-RUNBOOK.md": (
        "make gate-federation-doctrine",
        "srlab labctl federation-orient NONE",
        "every runtime stays",
        "`NOT_CHARACTERIZED`",
        "a caller-declared scope grants no authority",
    ),
    "TRADING-EXECUTION-BOUNDARY.md": (
        "Requests, intents, export packets and bridge",
        "Receipts retain receipt semantics",
        "runs retain evidence semantics",
        "Both remain authority-negative",
        "Market actions require the Market repository's native authority chain",
    ),
    "docs/architecture/README.md": (
        "SRL reasons.",
        "Target doctrine: Dual transports and orders; current deployment is unproven.",
        "No global sovereign writer or global A2 authority exists.",
    ),
    "docs/architecture/federated-research-organism-doctrine-v1.md": (
        "STATUS: DRAFT_PROPOSED",
        "PRIMARY_SCIENTIFIC_CORTEX: SCIENTIFIC_RESOURCE_LAB",
        "TARGET_WIRE_ORDER_OWNER: DUAL_CONTOUR",
        "TARGET_WIRE_ORDER_ROLE_STATE: TARGET_DECLARED_NOT_RUNTIME_PROVEN",
        "GLOBAL_SOVEREIGN_CONTROLLER: NONE",
        "GLOBAL_SOVEREIGN_WRITER: NONE",
        "GLOBAL_A2: FORBIDDEN",
        "CROSS_DOMAIN_EFFECT_OWNER: TARGET_NATIVE_DOMAIN_ONLY",
        "CROSSLAB_SRL_ENDPOINT: NONE",
        "CURRENT_FEDERATION_RUNTIME: NOT_CHARACTERIZED",
        "DECLARED_WRITE_SCOPE_GRANTS_AUTHORITY: FALSE",
        "## Exact reuse/delta matrix",
        "Any NO answer parks the change.",
    ),
    "docs/adr/0011-federated-research-organism-ownership.md": (
        "PRIMARY_SCIENTIFIC_CORTEX = SCIENTIFIC_RESOURCE_LAB",
        "GLOBAL_SOVEREIGN_WRITER = NONE",
        "GLOBAL_A2 = FORBIDDEN",
        "This ADR allocates target responsibility only.",
    ),
    "docs/architecture/transport.md": (
        "SCOPE: SRL_INTERNAL_FILE_BACKED_SPOOL",
        "NOT: TARGET_DUAL_WIRE",
        "TARGET_DUAL_WIRE_RUNTIME_PROVEN: false",
        "transport never reclassifies them",
    ),
    "docs/plans/federated-research-organism-successor-plan-v1.md": (
        "STATUS: DRAFT_PROPOSED",
        "MUTATES_V3_7_PLAN_OR_RECEIPTS: false",
        "GLOBAL_A2: FORBIDDEN",
        "## Current state",
        "## Target state",
        "## Semantic and wire boundary",
        "## Proposed work packages",
        "WAIT_GOVERNANCE_ADMISSION",
    ),
    "docs/integrations/MARKET-INTEGRATION.md": (
        "historical bound observations, not current Market runtime truth",
        "without it, report",
        "`NOT_CHARACTERIZED`",
    ),
    "docs/integrations/MARKET-CHILD-MISSION.md": (
        "recorded V3.7 A19 evidence generation",
        "not current Market runtime truth",
        "`NOT_CHARACTERIZED`",
    ),
    "docs/integrations/SECURITY-INTEGRATION.md": (
        "historical bound observations, not current Security runtime truth",
        "without it, report",
        "`NOT_CHARACTERIZED`",
    ),
    "docs/integrations/SECURITY-CHILD-MISSION.md": (
        "recorded V3.7 A20 evidence generation",
        "not current Security runtime truth",
        "`NOT_CHARACTERIZED`",
    ),
    "docs/integrations/shared-contracts.md": (
        "Historical V3.7 A18 target evidence",
        "not current",
        "report `NOT_CHARACTERIZED`",
    ),
    "src/srl/contracts/schemas/v1/README.md": (
        "proposal-payload import as C3",
        "cannot represent evidence or receipt import",
        "remain `WAIT_UNSUPPORTED` until a versioned successor",
        "SRF-local health pulse, independent of external cell health",
        "Read-only aggregation of cell status projections",
        "historical V3.7 evidence is never current runtime health",
    ),
}

FORBIDDEN_CLAIM_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"^\s*ACTUAL\s+GOVERNANCE\s*:", re.IGNORECASE | re.MULTILINE),
    re.compile(
        r"\bSRL\s+(?:IS|OWNS|HAS|ACTS\s+AS)\s+(?!NOT\b)(?:THE\s+|A\s+)?GLOBAL\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bDUAL\s+(?:IS|RUNTIME\s+IS)\s+ACTIVE\b", re.IGNORECASE),
    re.compile(
        r"\bSECURITY\s+IS\s+(?!NOT\b)(?:THE\s+|A\s+)?GLOBAL\s+BRAIN\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bCROSSLAB\s+(?:EXECUTES|GRANTS|OWNS)\s+(?!NO\b)"
        r"(?:AUTHORITY|EVIDENCE|ACTIONS?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:THE\s+)?GLOBAL\s+(?:SOVEREIGN\s+)?"
        r"(?:CONTROLLER|WRITER|A2\s+AUTHORITY)\s+(?:IS|BELONGS\s+TO|=)\s+SRL\b",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(
        r"(?<!NOT\sPROOF\sTHAT\n)^\s*DUAL(?:\s+CONTOUR|\s+WIRE)?\s+IS\s+"
        r"(?:ACTIVE|DEPLOYED|OPERATIONAL)(?:\s+AND\s+OPERATIONAL)?\b",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(
        r"\bCROSSLAB\s+(?:MAY\s+)?"
        r"(?:EXECUTES?|GRANTS?|AUTHORIZES?|TRIGGERS?|ACCEPTS?)\s+"
        r"(?:ACTIONS?|AUTHORITY|EVIDENCE|SRL\s+ENDPOINT)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bSRL\s+(?:MAY\s+)?(?!DOES\s+NOT\b|MAY\s+NOT\b)"
        r"(?:ISSUES?|SELECTS?|BYPASSES?|EXECUTES?|TRADES?|DEPLOYS?)\s+"
        r"(?:A2|NATIVE|MARKET|SECURITY|WRITERS?|PERMITS?|ACTIONS?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:GLOBAL_SOVEREIGN_CONTROLLER|GLOBAL_SOVEREIGN_WRITER|"
        r"GLOBAL_A2_AUTHORITY)[ \t]*[:=](?![ \t]*NONE[ \t]*$)[ \t]*[^\r\n]+",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(
        r"^\s*(?:CURRENT_DUAL_RUNTIME|FEDERATION_RUNTIME_STATE)\s*[:=]\s*"
        r"(?:ACTIVE|DEPLOYED|GREEN|OPERATIONAL)\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(
        r"^\s*CROSSLAB_SRL_ENDPOINT\s*[:=]\s*(?:ACTIVE|ENABLED|TRUE)\s*$",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(
        r"\b(?:SRL\s+SPOOL\s+(?:AND|\+)\s+DUAL\s+WIRE|"
        r"DUAL\s+WIRE\s+(?:AND|\+)\s+SRL\s+SPOOL)\b.{0,40}\bACTIVE\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bD3\s+(?:MAY|CAN|IS\s+ALLOWED\s+TO)\s+"
        r"(?:BE\s+)?(?:EXPORTED|HASHED|REFERENCED|LOGGED)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bRECEIPTS?(?:\s+AND\s+(?:VALIDATION\s+)?EVIDENCE)?\s+"
        r"(?:ARE|BECOME|REMAIN)\s+C3(?:/PROPOSAL-ONLY|\s+PROPOSALS?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:EVERY\s+)?NATIVE\s+WRITERS?\b.{0,100}\b"
        r"(?:SHALL|MUST|HAS\s+TO|NEEDS?\s+TO)\s+"
        r"(?:AWAIT|OBTAIN|RECEIVE)\b.{0,80}\bSRL(?:'S)?\s+"
        r"(?:APPROVAL|PERMIT|AUTHORIZATION)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bSRL\s+(?:IS\s+)?(?:ENTITLED|AUTHORIZED|EMPOWERED|PERMITTED)\s+TO\s+"
        r"(?:APPROVE|AUTHORIZE|PERMIT|ADMIT)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:PRODUCTION|CURRENT|LIVE|OPERATIONAL)\s+(?:CROSS-DOMAIN\s+)?"
        r"(?:TRAFFIC|MESSAGES?|REQUESTS?)\b.{0,80}\b(?:FLOWS?|ROUTES?|RUNS?)\b"
        r".{0,50}\bDUAL(?:\s+WIRE)?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bCROSSLAB\b.{0,60}\b(?:STARTS?|LAUNCHES?|RUNS?|EXECUTES?)\b"
        r".{0,60}\b(?:JOBS?|ACTIONS?|PROVIDERS?|WRITERS?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bSRL\b.{0,60}\b(?:RECEIVES?|CONSUMES?)\b.{0,80}\bCROSSLAB\b"
        r".{0,40}\bENDPOINT\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bSRL\s+SPOOL\b.{0,100}\bDUAL\s+WIRE\b.{0,100}\b"
        r"(?:EACH|INDEPENDENT|SIMULTANEOUS|BOTH)\b.{0,80}\b"
        r"(?:ORDER|AUTHORITY|LEDGER|BUS)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bRAW\s+D2\b.{0,100}\b(?:CROSSES?|EXPORTED?|SENT|TRANSMITTED|"
        r"UNCHANGED|REFERENCED?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bD3\b.{0,100}\b(?:ARE|IS|MAY|CAN|WILL)\b.{0,60}\b"
        r"(?:SENT|LOGGED|HASHED|REFERENCED|IDENTIFIED|EXPORTED)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:CONVERTS?|TURNS?|RECLASSIF(?:Y|IES))\b.{0,100}\b"
        r"(?:RECEIPTS?|VALIDATION|EVIDENCE)\b.{0,100}\b(?:C3|PROPOSAL)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:RECEIPTS?|VALIDATION|EVIDENCE)\b.{0,100}\b"
        r"(?:BECOMES?|IS\s+CONVERTED|ARE\s+CONVERTED|IS\s+RECLASSIFIED|"
        r"ARE\s+RECLASSIFIED)\b.{0,100}\b(?:C3|PROPOSAL)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:IMPORTS?|ACCEPTS?)\b.{0,100}\bC3\s+"
        r"(?:EVIDENCE|OBSERVATIONS?|FINDINGS?|RESULTS?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:SCIENTIFIC|SAFETY)\s+OUTPUT\b.{0,60}\bBECOMES?\s+C3\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bV2\.0\.0\b.{0,80}\b(?:IS|WAS|NOW)\s+"
        r"(?:PUBLISHED|RELEASED|LIVE)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:THE\s+)?FEDERATION\s+RUNTIME\s+(?:IS\s+)?"
        r"(?:OPERATIONAL|ACTIVE|GREEN|DEPLOYED)\b",
        re.IGNORECASE | re.MULTILINE,
    ),
)

MARKDOWN_LINK_RE: Final[re.Pattern[str]] = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON object key: {key}")
        value[key] = item
    return value


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_object_without_duplicate_keys,
        )
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot load JSON document {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON document {path.name} must be an object")
    return value


def _strict_equal(actual: object, expected: object) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual) != set(expected):
            return False
        return all(_strict_equal(actual[key], value) for key, value in expected.items())
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return False
        return all(_strict_equal(left, right) for left, right in zip(actual, expected, strict=True))
    return actual == expected


def _unique_string_set(value: object) -> set[str] | None:
    if not isinstance(value, list) or not all(type(item) is str for item in value):
        return None
    rendered = set(value)
    return rendered if len(rendered) == len(value) else None


def _canonical_bytes(value: object) -> bytes:
    rendered = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return (rendered + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _normalized_sha256(value: object) -> str | None:
    if type(value) is not str:
        return None
    digest = value.removeprefix("sha256:").replace("-", "")
    return "sha256:" + digest if re.fullmatch(r"[0-9a-f]{64}", digest) else None


def _documentation_receipt_id(receipt: dict[str, Any]) -> str:
    body = {key: value for key, value in receipt.items() if key != "receipt_id"}
    encoded = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return "-".join(digest[index : index + 8] for index in range(0, 64, 8))


def _normalize_policy_digest(value: str) -> str:
    return value.replace("-", "")


def _policy_digest_matches(value: object, actual: object) -> bool:
    return (
        type(value) is str
        and POLICY_DIGEST_RE.fullmatch(value) is not None
        and _normalize_policy_digest(value) == actual
    )


def _repo_file(repo_root: Path, relative_path: str) -> Path | None:
    """Resolve one regular in-repository file without following symlink components."""
    relative = Path(relative_path)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        return None
    try:
        if repo_root.is_symlink():
            return None
        root = repo_root.resolve(strict=True)
        cursor = repo_root
        for part in relative.parts:
            cursor /= part
            if cursor.is_symlink():
                return None
        resolved = (repo_root / relative).resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            return None
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved


def _git_environment() -> dict[str, str]:
    """Return a deterministic Git environment with ambient repository overrides removed."""
    return {
        "GIT_CONFIG_COUNT": "0",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }


def _run_git(
    repo_root: Path,
    *args: str,
    text: bool = False,
) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(  # noqa: S603
        ["/usr/bin/git", "-C", str(repo_root), *args],
        capture_output=True,
        check=False,
        env=_git_environment(),
        text=text,
    )


def _git_top_level_matches(repo_root: Path) -> bool:
    process = _run_git(repo_root, "rev-parse", "--show-toplevel", text=True)
    if process.returncode != 0:
        return False
    try:
        return Path(process.stdout.strip()).resolve(strict=True) == repo_root.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return False


def _git_head(repo_root: Path) -> str | None:
    if not _git_top_level_matches(repo_root):
        return None
    process = _run_git(repo_root, "rev-parse", "HEAD", text=True)
    value = process.stdout.strip()
    return value if process.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", value) else None


def _git_candidate_diff_sha256(repo_root: Path, base_head: str) -> str | None:
    """Hash the governed base-to-index candidate, stable across unrelated commits.

    The path set is explicit and itself covered by this verifier's hash. The two
    evidence receipts are absent from it to avoid a self-referential digest. An
    empty governed candidate fails closed instead of becoming the SHA-256 of
    empty bytes.
    """
    if not _git_top_level_matches(repo_root) or re.fullmatch(r"[0-9a-f]{40}", base_head) is None:
        return None
    current_head = _git_head(repo_root)
    if current_head is None:
        return None
    ancestor = _run_git(repo_root, "merge-base", "--is-ancestor", base_head, current_head)
    if ancestor.returncode != 0:
        return None
    governed_pathspecs = [f":(top,literal){path}" for path in CANDIDATE_GOVERNED_PATHS]
    process = _run_git(
        repo_root,
        "diff",
        "--cached",
        "--binary",
        "--full-index",
        "--no-color",
        "--no-ext-diff",
        "--no-renames",
        "--no-textconv",
        base_head,
        "--",
        *governed_pathspecs,
    )
    if process.returncode != 0 or not process.stdout:
        return None
    digest = _sha256_bytes(process.stdout)
    return digest if digest != EMPTY_SHA256 else None


def _git_worktree_matches_index(repo_root: Path) -> bool:
    if not _git_top_level_matches(repo_root):
        return False
    tracked = _run_git(repo_root, "diff", "--quiet", "--no-ext-diff")
    untracked = _run_git(
        repo_root,
        "ls-files",
        "--others",
        "--exclude-standard",
        text=True,
    )
    return tracked.returncode == 0 and untracked.returncode == 0 and not untracked.stdout.strip()


def _check(check_id: str, passed: bool, detail: str) -> dict[str, str]:
    return {
        "check_id": check_id,
        "status": "PASS" if passed else "FAIL",
        "detail": detail,
    }


def _participant_map(policy: dict[str, Any]) -> dict[str, Any]:
    participants = policy.get("participants")
    return participants if isinstance(participants, dict) else {}


def _metadata_checks(policy: dict[str, Any]) -> list[dict[str, str]]:
    metadata_ok = (
        set(policy) == EXPECTED_TOP_LEVEL_KEYS
        and policy.get("schema_version") == "FederationOwnershipPolicy/v1"
        and policy.get("policy_id") == "FEDERATION_OWNERSHIP_POLICY_V1"
        and policy.get("status") == "DRAFT_PROPOSED"
        and policy.get("activates_federation") is False
        and policy.get("runtime_truth") is False
        and type(policy.get("canonical_writes")) is int
        and policy.get("canonical_writes") == 0
        and policy.get("grants_authority") is False
    )
    return [
        _check(
            "FDC-01-policy-metadata",
            metadata_ok,
            "policy is DRAFT_PROPOSED, authority-negative and non-activating",
        ),
        _check(
            "FDC-02-formal-invariants",
            _strict_equal(policy.get("formal_invariants"), EXPECTED_FORMAL_INVARIANTS)
            and _strict_equal(policy.get("human_metaphor"), EXPECTED_HUMAN_METAPHOR)
            and _strict_equal(policy.get("semantic_invariants"), EXPECTED_SEMANTIC_INVARIANTS)
            and _strict_equal(policy.get("transport_transition"), EXPECTED_TRANSPORT_TRANSITION),
            "cortex, semantic classes, target wire and absent global authority are exact",
        ),
    ]


def _identity_check(participant_map: dict[str, Any]) -> dict[str, str]:
    identities_ok = set(participant_map) == set(EXPECTED_PARTICIPANTS)
    if identities_ok:
        for name, (repository_id, role_code) in EXPECTED_PARTICIPANTS.items():
            item = participant_map.get(name)
            if not isinstance(item, dict):
                identities_ok = False
                break
            if set(item) != EXPECTED_PARTICIPANT_KEYS[name]:
                identities_ok = False
                break
            if item.get("repository_id") != repository_id or item.get("role_code") != role_code:
                identities_ok = False
                break
            owns = _unique_string_set(item.get("owns"))
            excludes = _unique_string_set(item.get("does_not_own"))
            if owns is None or excludes is None or owns & excludes:
                identities_ok = False
                break
    return _check(
        "FDC-03-participant-identities",
        identities_ok,
        "participant set, repository identities and formal role codes are exact",
    )


def _srl_check(participant_map: dict[str, Any]) -> dict[str, str]:
    srl = participant_map.get("srl")
    srl_map = srl if isinstance(srl, dict) else {}
    owns = _unique_string_set(srl_map.get("owns")) == {
        "bounded_scientific_execution",
        "formal_and_numerical_reasoning",
        "scientific_capability_catalog",
        "srl_scientific_contract_semantics",
        "scientific_knowledge_and_provenance",
        "scientific_planner_and_router",
        "scientific_receipts",
        "shared_read_only_scientific_interface",
    }
    excludes = _unique_string_set(srl_map.get("does_not_own")) == {
        "cross_domain_delivery_order",
        "global_authority",
        "market_truth",
        "native_domain_admission",
        "native_domain_writers",
        "security_truth",
    }
    return _check(
        "FDC-04-srl-boundary",
        owns and excludes,
        "SRL owns cognition and excludes native truth, effects and wire order",
    )


def _dual_check(participant_map: dict[str, Any]) -> dict[str, str]:
    dual = participant_map.get("dual")
    dual_map = dual if isinstance(dual, dict) else {}
    owns = _unique_string_set(dual_map.get("owns")) == {
        "wire_acknowledgements",
        "wire_backpressure",
        "wire_deduplication",
        "wire_delivery_order",
        "wire_epoch_and_sequence",
        "wire_ledger_watermark",
    }
    excludes = _unique_string_set(dual_map.get("does_not_own")) == {
        "global_authority",
        "market_truth",
        "native_domain_effects",
        "scientific_payload_meaning",
        "scientific_validation",
        "security_truth",
    }
    mechanics_only = (
        dual_map.get("payload_reinterpretation_allowed") is False
        and dual_map.get("role_activation") == "TARGET_DECLARED_NOT_RUNTIME_PROVEN"
    )
    return _check(
        "FDC-05-dual-boundary",
        owns and excludes and mechanics_only,
        "Dual owns target wire mechanics only and cannot reinterpret scientific payloads",
    )


def _native_domain_check(participant_map: dict[str, Any]) -> dict[str, str]:
    market = participant_map.get("market")
    market_map = market if isinstance(market, dict) else {}
    security = participant_map.get("security")
    security_map = security if isinstance(security, dict) else {}
    market_owns = _unique_string_set(market_map.get("owns")) == {
        "market_domain_truth",
        "market_gates_and_admission",
        "market_material_event_projection",
        "market_native_writers",
    }
    market_excludes = _unique_string_set(market_map.get("does_not_own")) == {
        "global_transport_order",
        "security_truth",
        "srl_capability_truth",
    }
    security_owns = _unique_string_set(security_map.get("owns")) == {
        "safety_attention_and_verdicts",
        "security_domain_truth",
        "security_native_admission",
        "security_native_executor_boundary",
        "security_native_writers",
    }
    security_excludes = _unique_string_set(security_map.get("does_not_own")) == {
        "general_scientific_planning",
        "global_transport_order",
        "market_truth",
        "srl_scientific_contract_semantics",
    }
    return _check(
        "FDC-06-native-truth-and-effects",
        market_owns and market_excludes and security_owns and security_excludes,
        "Market and Security retain disjoint native truth, admission and effect ownership",
    )


def _crosslab_check(participant_map: dict[str, Any]) -> dict[str, str]:
    crosslab = participant_map.get("crosslab")
    crosslab_map = crosslab if isinstance(crosslab, dict) else {}
    pager_only = _unique_string_set(crosslab_map.get("owns")) == {
        "wake_notification_of_immutable_reference"
    }
    excludes = _unique_string_set(crosslab_map.get("does_not_own")) == {
        "authority",
        "evidence",
        "execution",
        "queue_semantics",
        "transport_truth",
    }
    return _check(
        "FDC-07-crosslab-pager-only",
        pager_only
        and excludes
        and _strict_equal(
            crosslab_map.get("registered_peer_scope"), ["bridge", "market", "security"]
        )
        and crosslab_map.get("srl_endpoint_allowed") is False,
        "CrossLab is notification-only and owns no evidence, execution, queue or authority",
    )


def _wire_check(policy: dict[str, Any]) -> dict[str, str]:
    wire = policy.get("wire_semantic_boundary")
    wire_map = wire if isinstance(wire, dict) else {}
    expected = {
        "dual_may_reinterpret_scientific_payload": False,
        "dual_wraps": "exact_scientific_payload_bytes_or_immutable_reference",
        "scientific_object_id_equals_wire_document_id": False,
        "srl_internal_spool_is_global_wire": False,
        "transport_ack_grants_application_acceptance": False,
    }
    return _check(
        "FDC-08-wire-semantic-separation",
        _strict_equal(wire_map, expected),
        "scientific payload identity and wire identity remain separate",
    )


def _current_truth_check(repo_root: Path, policy: dict[str, Any]) -> dict[str, str]:
    current = policy.get("current_state")
    current_map = current if isinstance(current, dict) else {}
    release_path = current_map.get("release_truth_path")
    release_ok = _strict_equal(current_map, EXPECTED_CURRENT_STATE) and isinstance(
        release_path, str
    )
    if release_ok:
        resolved_release_path = _repo_file(repo_root, release_path)
        if resolved_release_path is None:
            release_ok = False
    if release_ok:
        try:
            release = _load_json(resolved_release_path)
        except ValueError:
            release_ok = False
        else:
            release_body = {key: value for key, value in release.items() if key != "receipt_id"}
            computed_receipt_id = _sha256_bytes(_canonical_bytes(release_body))
            release_state = release.get("release")
            release_state_map = release_state if isinstance(release_state, dict) else {}
            decision = release.get("release_truth_decision")
            decision_map = decision if isinstance(decision, dict) else {}
            provenance = release.get("head_provenance")
            provenance_map = provenance if isinstance(provenance, dict) else {}
            waits = release.get("remaining_external_waits")
            release_ok = (
                release.get("schema_version") == "MissionCloseoutReceipt/v2"
                and release.get("mission_id") == "activate-scientific-reasoning-fabric-v3.7"
                and release.get("stage_id") == "A22"
                and release.get("result") == "BLOCKED_EXTERNAL_AUTHORITY"
                and release.get("target_release") == "v2.0.0"
                and release.get("target_result") == "DONE"
                and release.get("receipt_id") == current_map.get("release_truth_receipt_id")
                and release.get("receipt_id") == computed_receipt_id
                and release.get("accepted_release_head") == current_map.get("accepted_release_head")
                and provenance_map.get("accepted_release_head")
                == current_map.get("accepted_release_head")
                and release_state_map.get("published") is False
                and release_state_map.get("tag") is None
                and decision_map.get("verdict") == "REJECT"
                and decision_map.get("target_release") == "v2.0.0"
                and decision_map.get("target_result") == "DONE"
                and _strict_equal(
                    release.get("forbidden_terminal_states"),
                    ["DONE", "RELEASED_WITH_DECLARED_WAITS"],
                )
                and isinstance(waits, list)
                and bool(waits)
                and all(type(item) is str for item in waits)
                and type(release.get("canonical_writes")) is int
                and release.get("canonical_writes") == 0
                and type(release.get("live_actions")) is int
                and release.get("live_actions") == 0
                and release.get("grants_authority") is False
                and current_map.get("release_truth_result") == "BLOCKED_EXTERNAL_AUTHORITY"
                and current_map.get("federation_state_source")
                == "exact_current_native_receipts_only"
                and current_map.get("role_allocation_is_runtime_evidence") is False
            )
    return _check(
        "FDC-09-current-vs-static-truth",
        release_ok,
        "static policy is bound to the exact content-addressed blocked V3.7 closeout",
    )


def _entrypoint_marker_failures(repo_root: Path) -> tuple[dict[str, str], list[str]]:
    missing: list[str] = []
    texts: dict[str, str] = {}
    for relative_path, markers in REQUIRED_DOC_MARKERS.items():
        path = _repo_file(repo_root, relative_path)
        if path is None:
            missing.append(f"{relative_path}:unsafe_or_missing")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            missing.append(relative_path)
            continue
        texts[relative_path] = text
        for marker in markers:
            if marker not in text:
                missing.append(f"{relative_path}:{marker}")
        for pattern in FORBIDDEN_CLAIM_PATTERNS:
            if pattern.search(text):
                missing.append(f"{relative_path}:forbidden:{pattern.pattern}")
        eof_marker = DOCUMENT_EOF_MARKERS.get(relative_path)
        if eof_marker is not None and not text.endswith(eof_marker + "\n"):
            missing.append(f"{relative_path}:exact_eof_marker")
    return texts, missing


def _entrypoint_check(repo_root: Path) -> dict[str, str]:
    texts, missing = _entrypoint_marker_failures(repo_root)

    doctrine = texts.get("docs/architecture/federated-research-organism-doctrine-v1.md", "")
    agents = texts.get("AGENTS.md", "")
    if doctrine.count(DOCTRINE_ORIENTATION_BLOCK) != 1:
        missing.append("doctrine:exact_orientation_block")
    if agents.count(AGENT_ORIENTATION_BLOCK) != 1:
        missing.append("AGENTS:exact_orientation_block")
    if re.search(r"^WIRE_ORDER_OWNER:", doctrine + "\n" + agents, re.MULTILINE):
        missing.append("obsolete_wire_order_owner_field")
    if re.search(r"^GLOBAL_A2_AUTHORITY:", doctrine + "\n" + agents, re.MULTILINE):
        missing.append("obsolete_global_a2_authority_field")
    doc_markers_ok = not missing
    detail = (
        "all mandatory root and architecture entrypoints carry exact role markers"
        if doc_markers_ok
        else f"missing markers: {sorted(missing)}"
    )
    return _check(
        "FDC-10-mandatory-entrypoints",
        doc_markers_ok,
        detail,
    )


def _document_hashes(repo_root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for relative_path in BOUND_DOCUMENT_PATHS:
        path = _repo_file(repo_root, relative_path)
        if path is None:
            hashes[relative_path] = "MISSING_OR_UNSAFE"
            continue
        try:
            hashes[relative_path] = _sha256_file(path)
        except OSError:
            hashes[relative_path] = "MISSING"
    return hashes


def _document_binding_check(
    policy: dict[str, Any], document_hashes: dict[str, str]
) -> dict[str, str]:
    bindings = policy.get("document_bindings")
    bindings_map = bindings if isinstance(bindings, dict) else {}
    valid = set(bindings_map) == set(BOUND_DOCUMENT_PATHS)
    if valid:
        valid = all(
            _policy_digest_matches(value, document_hashes.get(path))
            for path, value in bindings_map.items()
        )
    return _check(
        "FDC-11-document-bindings",
        valid,
        "role-bearing documents are exact-hash-bound to the ownership policy",
    )


def _source_hashes(repo_root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for relative_path in BOUND_SOURCE_PATHS:
        path = _repo_file(repo_root, relative_path)
        if path is None:
            hashes[relative_path] = "MISSING_OR_UNSAFE"
            continue
        try:
            hashes[relative_path] = _sha256_file(path)
        except OSError:
            hashes[relative_path] = "MISSING"
    return hashes


def _source_binding_check(policy: dict[str, Any], source_hashes: dict[str, str]) -> dict[str, str]:
    bindings = policy.get("source_bindings")
    bindings_map = bindings if isinstance(bindings, dict) else {}
    valid = set(bindings_map) == set(BOUND_SOURCE_PATHS)
    if valid:
        valid = all(
            _policy_digest_matches(value, source_hashes.get(path))
            for path, value in bindings_map.items()
        )
    return _check(
        "FDC-14-source-bindings",
        valid,
        "role-generating sources and D0/D1 contract surfaces are exact-hash-bound",
    )


def _bound_json(repo_root: Path, relative_path: str) -> dict[str, Any]:
    path = _repo_file(repo_root, relative_path)
    if path is None:
        raise ValueError(f"unsafe or missing bound JSON file: {relative_path}")
    return _load_json(path)


def _documentation_closure_check(
    repo_root: Path,
    input_manifest: dict[str, object],
) -> dict[str, str]:
    path = _repo_file(repo_root, DOCUMENTATION_CLOSURE_RECEIPT_PATH)
    if path is None:
        return _check(
            "FDC-16-documentation-closure-binding",
            False,
            "documentation closure receipt is absent, unsafe or a symlink",
        )
    try:
        receipt = _load_json(path)
        historical = _bound_json(repo_root, HISTORICAL_DOCUMENTATION_RECEIPT_PATH)
        system_acceptance = _bound_json(repo_root, SYSTEM_ACCEPTANCE_RECEIPT_PATH)
    except ValueError as exc:
        return _check("FDC-16-documentation-closure-binding", False, str(exc))

    expected_keys = {
        "activates_federation",
        "canonical_writes",
        "checks",
        "generated_source_sha256",
        "grants_authority",
        "historical_receipt_unchanged",
        "limitations",
        "live_actions",
        "protected_actions",
        "receipt_id",
        "required_doc_sha256",
        "required_docs",
        "result",
        "runtime_truth",
        "schema_version",
        "source_head",
        "source_head_role",
        "source_system_acceptance_receipt",
        "staged_candidate_diff_sha256",
        "supersedes_receipt_id",
        "work_package",
    }
    protected = receipt.get("protected_actions")
    protected_map = protected if isinstance(protected, dict) else {}
    required_docs = receipt.get("required_docs")
    required_doc_hashes = receipt.get("required_doc_sha256")
    required_doc_hash_map = required_doc_hashes if isinstance(required_doc_hashes, dict) else {}
    generated_hashes = receipt.get("generated_source_sha256")
    generated_hash_map = generated_hashes if isinstance(generated_hashes, dict) else {}
    checks = receipt.get("checks")
    checks_list = checks if isinstance(checks, list) else []
    expected_check_ids = {
        "link_check",
        "markdown_structure",
        "public_boundary",
        "secret_scan",
        "solo_docs_check",
        "system_docs_check",
    }
    observed_check_ids = {
        item.get("check_id")
        for item in checks_list
        if isinstance(item, dict)
        and set(item) == {"check_id", "command", "exit_code", "status"}
        and isinstance(item.get("command"), str)
        and bool(item.get("command"))
        and type(item.get("exit_code")) is int
        and item.get("exit_code") == 0
        and item.get("status") == "PASS"
    }

    required_hashes_valid = (
        _strict_equal(required_docs, list(DOCUMENTATION_REQUIRED_PATHS))
        and set(required_doc_hash_map) == set(DOCUMENTATION_REQUIRED_PATHS)
        and all(
            (bound := _repo_file(repo_root, relative_path)) is not None
            and _normalized_sha256(required_doc_hash_map.get(relative_path)) == _sha256_file(bound)
            for relative_path in DOCUMENTATION_REQUIRED_PATHS
        )
    )
    generated_hashes_valid = set(generated_hash_map) == set(
        DOCUMENTATION_GENERATED_SOURCE_PATHS
    ) and all(
        (bound := _repo_file(repo_root, relative_path)) is not None
        and _normalized_sha256(generated_hash_map.get(relative_path)) == _sha256_file(bound)
        for relative_path in DOCUMENTATION_GENERATED_SOURCE_PATHS
    )
    valid = (
        set(receipt) == expected_keys
        and receipt.get("schema_version") == "DocumentationClosureReceipt/v2"
        and receipt.get("work_package") == "GOV-FED-01"
        and receipt.get("source_head") == input_manifest.get("candidate_base_head")
        and receipt.get("source_head_role") == "base_head_for_frozen_staged_candidate"
        and _normalized_sha256(receipt.get("staged_candidate_diff_sha256"))
        == input_manifest.get("candidate_diff_sha256")
        and receipt.get("supersedes_receipt_id") == historical.get("receipt_id")
        and _normalized_sha256(receipt.get("source_system_acceptance_receipt"))
        == _normalized_sha256(system_acceptance.get("receipt_id"))
        and required_hashes_valid
        and generated_hashes_valid
        and observed_check_ids == expected_check_ids
        and len(checks_list) == len(expected_check_ids)
        and _strict_equal(
            receipt.get("limitations"),
            [
                "static_target_doctrine_only",
                "does_not_characterize_current_market_security_or_dual_runtime",
                "does_not_activate_federation_or_publish_v2_0_0",
            ],
        )
        and receipt.get("result") == "PASS"
        and receipt.get("runtime_truth") is False
        and receipt.get("activates_federation") is False
        and type(receipt.get("canonical_writes")) is int
        and receipt.get("canonical_writes") == 0
        and type(receipt.get("live_actions")) is int
        and receipt.get("live_actions") == 0
        and receipt.get("grants_authority") is False
        and receipt.get("historical_receipt_unchanged") is True
        and set(protected_map) == {"performed", "wait_states"}
        and _strict_equal(protected_map.get("performed"), [])
        and _strict_equal(
            protected_map.get("wait_states"),
            ["WAIT_T7_BINDING", "WAIT_COMPUTE_NODE"],
        )
        and receipt.get("receipt_id") == _documentation_receipt_id(receipt)
    )
    return _check(
        "FDC-16-documentation-closure-binding",
        valid,
        "documentation closure receipt binds the exact non-empty candidate and base HEAD"
        if valid
        else "documentation closure receipt is stale, malformed or authority-positive",
    )


def _repository_file_containment_check(
    repo_root: Path,
    policy: dict[str, Any],
) -> dict[str, str]:
    current_state = policy.get("current_state")
    current_map = current_state if isinstance(current_state, dict) else {}
    release_path = current_map.get("release_truth_path")
    paths = [
        *BOUND_DOCUMENT_PATHS,
        *BOUND_SOURCE_PATHS,
        *DOCUMENTATION_REQUIRED_PATHS,
        *DOCUMENTATION_GENERATED_SOURCE_PATHS,
        DEFAULT_POLICY_PATH,
        *EVIDENCE_RECEIPT_PATHS,
        HISTORICAL_DOCUMENTATION_RECEIPT_PATH,
        SYSTEM_ACCEPTANCE_RECEIPT_PATH,
    ]
    if isinstance(release_path, str):
        paths.append(release_path)
    invalid = sorted({path for path in paths if _repo_file(repo_root, path) is None})
    return _check(
        "FDC-17-repository-file-containment",
        not invalid,
        "all bound documents, sources and receipts are regular contained files"
        if not invalid
        else f"unsafe, missing or symlinked bound files: {invalid}",
    )


def _critical_source_semantics_check(  # noqa: C901, PLR0912, PLR0915
    repo_root: Path,
) -> dict[str, str]:
    failures: list[str] = []
    try:
        makefile_path = _repo_file(repo_root, "Makefile")
        if makefile_path is None:
            failures.append("unsafe_or_missing:Makefile")
        else:
            makefile_text = makefile_path.read_text(encoding="utf-8")
            exact_target = (
                "gate-federation-doctrine: ## Verify static federation ownership and "
                "mandatory role entrypoints.\n"
                "\tuv run python scripts/checks/federation-doctrine-consistency.py"
            )
            if (
                makefile_text.count("gate-federation-doctrine:") != 1
                or exact_target not in makefile_text
            ):
                failures.append("makefile_federation_gate_entrypoint")

        workflow_path = _repo_file(repo_root, ".github/workflows/docs.yml")
        if workflow_path is None:
            failures.append("unsafe_or_missing:.github/workflows/docs.yml")
        else:
            workflow_text = workflow_path.read_text(encoding="utf-8")
            exact_job = """  federation-doctrine:
    name: federation doctrine
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    steps:
      - name: Checkout full governance history
        uses: actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09  # v5.1.0
        with:
          fetch-depth: 0
          persist-credentials: false
      - name: Federation doctrine consistency
        run: python3 scripts/checks/federation-doctrine-consistency.py
"""
            if (
                workflow_text.count("  federation-doctrine:\n") != 1
                or exact_job not in workflow_text
            ):
                failures.append("github_federation_gate_job")

        spool_path = _repo_file(repo_root, "src/srl/transport/spool.py")
        if spool_path is None:
            raise ValueError("unsafe or missing SRL spool source")
        spool_text = spool_path.read_text(encoding="utf-8").lower()
        for token in (
            "dual_wire",
            "dual wire",
            "dual-contour",
            "crosslab",
            "cross_lab",
            "active_cross_domain",
        ):
            if token in spool_text:
                failures.append(f"spool_second_bus_token:{token}")

        ack = _bound_json(repo_root, "src/srl/contracts/schemas/v1/spool-ack.json")
        ack_properties = ack.get("properties")
        ack_map = ack_properties if isinstance(ack_properties, dict) else {}
        ack_status = ack_map.get("ack_status")
        ack_status_map = ack_status if isinstance(ack_status, dict) else {}
        if not (
            ack.get("type") == "object"
            and ack.get("additionalProperties") is False
            and _strict_equal(
                ack.get("required"),
                [
                    "schema_version",
                    "ack_id",
                    "message_id",
                    "ack_status",
                    "created_utc",
                    "canonical_writes",
                    "grants_authority",
                ],
            )
            and _strict_equal(
                ack_map.get("schema_version"),
                {"type": "string", "const": "SpoolAck/v1"},
            )
            and _strict_equal(
                ack_status_map.get("enum"),
                ["ACKNOWLEDGED", "DUPLICATE", "REJECTED", "EXPIRED", "QUARANTINED"],
            )
            and _strict_equal(ack_map.get("canonical_writes"), {"type": "integer", "const": 0})
            and _strict_equal(ack_map.get("grants_authority"), {"type": "boolean", "const": False})
        ):
            failures.append("spool_ack_semantics")

        authority_negative_schemas = {
            "src/srl/contracts/schemas/v1/evidence-assessment.json": ("EvidenceAssessment/v1"),
            "src/srl/contracts/schemas/v1/federation-status.json": ("FederationStatus/v1"),
            "src/srl/contracts/schemas/v1/lab-cell-manifest.json": ("LabCellManifest/v1"),
            "src/srl/contracts/schemas/v1/lab-export-packet.json": ("LabExportPacket/v1"),
            "src/srl/contracts/schemas/v1/lab-federation-manifest.json": (
                "LabFederationManifest/v1"
            ),
            "src/srl/contracts/schemas/v1/science-lab-run-receipt.json": (
                "ScienceLabRunReceipt/v1"
            ),
            "src/srl/contracts/schemas/v1/scientific-object-envelope.json": (
                "ScientificObjectEnvelope/v1"
            ),
            "src/srl/contracts/schemas/v1/scientific-request-envelope.json": (
                "ScientificRequestEnvelope/v1"
            ),
            "src/srl/contracts/schemas/v1/scientific-result-envelope.json": (
                "ScientificResultEnvelope/v1"
            ),
            "src/srl/contracts/schemas/v1/scientific-run-receipt.json": ("ScientificRunReceipt/v1"),
            "src/srl/contracts/schemas/v1/spool-message.json": "SpoolMessage/v1",
            "src/srl/contracts/schemas/v1/srf-pulse.json": "SRFPulse/v1",
            "src/srl/contracts/schemas/v1/transformation-receipt.json": (
                "TransformationReceipt/v1"
            ),
        }
        for relative_path, schema_version in authority_negative_schemas.items():
            schema = _bound_json(repo_root, relative_path)
            schema_properties = schema.get("properties")
            schema_map = schema_properties if isinstance(schema_properties, dict) else {}
            required = schema.get("required")
            required_set = set(required) if isinstance(required, list) else set()
            if not (
                schema.get("type") == "object"
                and schema.get("additionalProperties") is False
                and {"schema_version", "canonical_writes", "grants_authority"} <= required_set
                and isinstance(schema_map.get("schema_version"), dict)
                and schema_map["schema_version"].get("type") == "string"
                and schema_map["schema_version"].get("const") == schema_version
                and isinstance(schema_map.get("canonical_writes"), dict)
                and schema_map["canonical_writes"].get("type") == "integer"
                and type(schema_map["canonical_writes"].get("const")) is int
                and schema_map["canonical_writes"].get("const") == 0
                and isinstance(schema_map.get("grants_authority"), dict)
                and schema_map["grants_authority"].get("type") == "boolean"
                and schema_map["grants_authority"].get("const") is False
            ):
                failures.append(f"authority_negative_schema:{relative_path}")

        export_packet = _bound_json(
            repo_root, "src/srl/contracts/schemas/v1/lab-export-packet.json"
        )
        export_properties = export_packet.get("properties")
        export_map = export_properties if isinstance(export_properties, dict) else {}
        if not (
            isinstance(export_map.get("review_only"), dict)
            and export_map["review_only"].get("type") == "boolean"
            and export_map["review_only"].get("const") is True
            and isinstance(export_map.get("canonical_effect"), dict)
            and export_map["canonical_effect"].get("type") == "string"
            and export_map["canonical_effect"].get("const") == "none"
        ):
            failures.append("lab_export_packet_safety")

        autonomy = _bound_json(repo_root, "automation/policy.json")
        safety_false = (
            "canonical_runtime_mutation",
            "deployment_allowed",
            "external_pr_auto_merge",
            "secret_use_in_public_ci",
            "self_hosted_runner_allowed",
            "t7_execution_allowed",
            "vps_expansion_allowed",
        )
        if (
            autonomy.get("schema_version") != "AutonomyPolicy/v3"
            or type(autonomy.get("max_parallel_implementation_lanes")) is not int
            or autonomy.get("max_parallel_implementation_lanes")
            != EXPECTED_MAX_PARALLEL_IMPLEMENTATION_LANES
            or type(autonomy.get("max_scientific_execution_wip")) is not int
            or autonomy.get("max_scientific_execution_wip") != 1
            or any(autonomy.get(key) is not False for key in safety_false)
        ):
            failures.append("autonomy_policy_safety")

        state_schema = _bound_json(repo_root, "automation/state.schema.json")
        state_properties = state_schema.get("properties")
        state_map = state_properties if isinstance(state_properties, dict) else {}
        max_lanes = state_map.get("max_lanes")
        max_lanes_map = max_lanes if isinstance(max_lanes, dict) else {}
        active_lanes = state_map.get("active_lanes")
        active_lanes_map = active_lanes if isinstance(active_lanes, dict) else {}
        scientific_wip = state_map.get("scientific_wip")
        scientific_wip_map = scientific_wip if isinstance(scientific_wip, dict) else {}
        if not (
            max_lanes_map.get("const") == autonomy.get("max_parallel_implementation_lanes")
            and active_lanes_map.get("maxItems")
            == autonomy.get("max_parallel_implementation_lanes")
            and scientific_wip_map.get("maxItems") == autonomy.get("max_scientific_execution_wip")
        ):
            failures.append("autonomy_state_policy_cap")

        for domain in ("market", "security"):
            bridge = _bound_json(repo_root, f"configs/integrations/{domain}-bridge.json")
            domain_safe = (
                bridge.get("activation_state") == "INACTIVE"
                and bridge.get("runtime_truth") is False
                and bridge.get("current_native_runtime_characterization") == "NOT_CHARACTERIZED"
                and bridge.get("semantic_class") == "C3_PROPOSAL"
                and bridge.get("semantic_kind") == "PROPOSAL"
                and bridge.get("authority_effect") == "NONE"
                and _strict_equal(bridge.get("allowed_classifications"), ["D0", "D1"])
                and bridge.get("native_admission_required") is True
                and bridge.get("recorded_dependency_status_is_current_runtime_truth") is False
                and type(bridge.get("canonical_writes")) is int
                and bridge.get("canonical_writes") == 0
                and bridge.get("grants_authority") is False
            )
            if domain == "market":
                domain_safe = (
                    domain_safe
                    and bridge.get("market_writes") == 0
                    and bridge.get("live_actions") == 0
                    and bridge.get("trading_allowed") is False
                    and bridge.get("central_projector_required") is True
                    and "second_ledger" in bridge.get("forbidden", [])
                )
            else:
                domain_safe = (
                    domain_safe
                    and bridge.get("security_actions") == 0
                    and bridge.get("target_actions") == 0
                    and bridge.get("D2_D3_transfers") == 0
                    and bridge.get("direct_scanner_control") is False
                    and bridge.get("native_executor_boundary") == "ebashim"
                )
            if not domain_safe:
                failures.append(f"{domain}_bridge_config")

        import_schema = _bound_json(
            repo_root, "src/srl/contracts/schemas/v1/scientific-import-receipt.json"
        )
        import_properties = import_schema.get("properties")
        import_map = import_properties if isinstance(import_properties, dict) else {}
        import_status = import_map.get("import_status")
        import_status_map = import_status if isinstance(import_status, dict) else {}
        if not (
            import_schema.get("type") == "object"
            and import_schema.get("additionalProperties") is False
            and _strict_equal(
                import_schema.get("required"),
                [
                    "schema_version",
                    "receipt_id",
                    "source_packet_id",
                    "import_status",
                    "created_utc",
                    "canonical_writes",
                    "grants_authority",
                ],
            )
            and _strict_equal(
                import_status_map.get("enum"),
                ["IMPORTED_AS_C3", "REJECTED", "QUARANTINED", "DUPLICATE"],
            )
            and _strict_equal(import_map.get("canonical_writes"), {"type": "integer", "const": 0})
            and _strict_equal(
                import_map.get("grants_authority"), {"type": "boolean", "const": False}
            )
        ):
            failures.append("legacy_proposal_import_schema")

        orientation = _bound_json(
            repo_root,
            "src/srl/contracts/schemas/v1/federation-orientation-report.json",
        )
        orientation_properties = orientation.get("properties")
        orientation_map = orientation_properties if isinstance(orientation_properties, dict) else {}
        if not (
            orientation.get("type") == "object"
            and orientation.get("additionalProperties") is False
            and _strict_equal(
                orientation_map.get("schema_version"),
                {"type": "string", "const": "FederationOrientationReport/v1"},
            )
            and _strict_equal(
                orientation_map.get("runtime_truth"),
                {"type": "boolean", "const": False},
            )
            and _strict_equal(
                orientation_map.get("activates_federation"),
                {"type": "boolean", "const": False},
            )
            and _strict_equal(
                orientation_map.get("canonical_writes"),
                {"type": "integer", "const": 0},
            )
            and _strict_equal(
                orientation_map.get("live_actions"),
                {"type": "integer", "const": 0},
            )
            and _strict_equal(
                orientation_map.get("grants_authority"),
                {"type": "boolean", "const": False},
            )
            and _strict_equal(
                orientation_map.get("declared_scope_grants_authority"),
                {"type": "boolean", "const": False},
            )
        ):
            failures.append("federation_orientation_schema")

        schema_registry = _repo_file(repo_root, "src/srl/contracts/schema.py")
        if schema_registry is None:
            failures.append("unsafe_or_missing:schema_registry")
        elif (
            '"FederationOrientationReport": "federation-orientation-report.json"'
            not in schema_registry.read_text(encoding="utf-8")
        ):
            failures.append("federation_orientation_schema_registry")

        labctl = _repo_file(repo_root, "src/srl/labctl.py")
        if labctl is None:
            failures.append("unsafe_or_missing:src/srl/labctl.py")
        else:
            labctl_text = labctl.read_text(encoding="utf-8")
            orientation_snippets = (
                '"TARGET_WIRE_ORDER_OWNER": "DUAL_CONTOUR"',
                '"TARGET_WIRE_ORDER_ROLE_STATE": "TARGET_DECLARED_NOT_RUNTIME_PROVEN"',
                '"GLOBAL_SOVEREIGN_CONTROLLER": "NONE"',
                '"GLOBAL_SOVEREIGN_WRITER": "NONE"',
                '"GLOBAL_A2": "FORBIDDEN"',
                '"CROSS_DOMAIN_EFFECT_OWNER": "TARGET_NATIVE_DOMAIN_ONLY"',
                '"CROSSLAB_SRL_ENDPOINT": "NONE"',
                '"CURRENT_FEDERATION_RUNTIME": "NOT_CHARACTERIZED"',
                '"DECLARED_WRITE_SCOPE_GRANTS_AUTHORITY": False',
                'gate_manifest["candidate_base_head"]',
                'gate_manifest["candidate_diff_sha256"]',
            )
            if any(snippet not in labctl_text for snippet in orientation_snippets):
                failures.append("federation_orientation_source")

        bridge_snippets = {
            "src/srl/integrations/market/bridge.py": (
                'semantic_class: str = "C3_PROPOSAL"',
                '"activation_state": "INACTIVE"',
                "does not import native evidence or reclassify evidence as C3",
            ),
            "src/srl/integrations/security/bridge.py": (
                'semantic_class: str = "C3_PROPOSAL"',
                '"activation_state": "INACTIVE"',
                "does not\n    import native evidence or reclassify evidence as C3",
            ),
        }
        for relative_path, snippets in bridge_snippets.items():
            path = _repo_file(repo_root, relative_path)
            if path is None:
                failures.append(f"unsafe_or_missing:{relative_path}")
                continue
            text = path.read_text(encoding="utf-8")
            normalized_text = " ".join(text.split())
            if any(" ".join(snippet.split()) not in normalized_text for snippet in snippets):
                failures.append(f"legacy_bridge_semantics:{relative_path}")
    except (OSError, TypeError, ValueError) as exc:
        failures.append(str(exc))

    return _check(
        "FDC-18-critical-source-semantics",
        not failures,
        "governance entrypoints, SRL spool, ACK, autonomy and "
        "proposal-only bridge semantics are exact"
        if not failures
        else f"critical source semantic failures: {sorted(failures)}",
    )


def _v37_history_immutability_check(
    repo_root: Path,
    base_head: str = EXPECTED_CANDIDATE_BASE_HEAD,
) -> dict[str, str]:
    process = _run_git(
        repo_root,
        "diff",
        "--quiet",
        "--no-ext-diff",
        base_head,
        "--",
        *V37_IMMUTABLE_PATHS,
    )
    return _check(
        "FDC-19-v37-history-immutability",
        process.returncode == 0,
        "the V3.7 master plan and all V3.7 receipts are byte-identical to the base"
        if process.returncode == 0
        else "the V3.7 master plan or a V3.7 receipt changed, or the base is unavailable",
    )


def _independent_review_check(
    repo_root: Path,
    input_manifest: dict[str, object],
) -> dict[str, str]:
    path = _repo_file(repo_root, INDEPENDENT_REVIEW_RECEIPT_PATH)
    if path is None:
        return _check(
            "FDC-15-independent-review",
            False,
            "independent review receipt is absent, unsafe or a symlink",
        )
    try:
        receipt = _load_json(path)
    except ValueError as exc:
        return _check("FDC-15-independent-review", False, str(exc))

    expected_keys = {
        "activates_federation",
        "author",
        "base_head",
        "candidate_diff_sha256",
        "canonical_writes",
        "checks",
        "grants_authority",
        "live_actions",
        "receipt_id",
        "residual_risks",
        "reviewer",
        "schema_version",
        "verdict",
        "work_package",
    }
    checks = receipt.get("checks")
    checks_list = checks if isinstance(checks, list) else []
    required_check_ids = {
        "authority_and_native_sovereignty",
        "current_vs_target_truth",
        "generated_docs_and_machine_source",
        "hostile_consistency_tests",
        "ownership_raci",
        "reuse_delta_no_duplication",
        "semantic_wire_boundary",
        "v37_history_immutability",
    }
    observed_check_ids = {
        item.get("check_id")
        for item in checks_list
        if isinstance(item, dict)
        and set(item) == {"check_id", "detail", "status"}
        and item.get("status") == "PASS"
        and isinstance(item.get("detail"), str)
        and bool(item.get("detail"))
    }
    residual_risks = receipt.get("residual_risks")
    receipt_body = {key: value for key, value in receipt.items() if key != "receipt_id"}
    author = receipt.get("author")
    reviewer = receipt.get("reviewer")
    valid = (
        set(receipt) == expected_keys
        and receipt.get("schema_version") == "FederationDoctrineIndependentReviewReceipt/v1"
        and receipt.get("work_package") == "GOV-FED-01"
        and isinstance(author, str)
        and bool(author)
        and isinstance(reviewer, str)
        and bool(reviewer)
        and author != reviewer
        and receipt.get("base_head") == input_manifest.get("candidate_base_head")
        and _normalized_sha256(receipt.get("candidate_diff_sha256"))
        == input_manifest.get("candidate_diff_sha256")
        and receipt.get("verdict") == "APPROVE"
        and observed_check_ids == required_check_ids
        and len(checks_list) == len(required_check_ids)
        and isinstance(residual_risks, list)
        and all(isinstance(item, str) and bool(item) for item in residual_risks)
        and receipt.get("canonical_writes") == 0
        and receipt.get("live_actions") == 0
        and receipt.get("grants_authority") is False
        and receipt.get("activates_federation") is False
        and receipt.get("receipt_id") == _sha256_bytes(_canonical_bytes(receipt_body))
    )
    return _check(
        "FDC-15-independent-review",
        valid,
        "author-distinct review approves the exact frozen candidate diff"
        if valid
        else "independent review receipt is absent, stale, malformed or not approving",
    )


def _local_link_check(repo_root: Path) -> dict[str, str]:
    broken: list[str] = []
    for relative_path in BOUND_DOCUMENT_PATHS:
        if not relative_path.endswith(".md"):
            continue
        path = _repo_file(repo_root, relative_path)
        if path is None:
            broken.append(f"{relative_path}:unsafe_or_missing")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            broken.append(relative_path)
            continue
        for raw_target in MARKDOWN_LINK_RE.findall(text):
            target = raw_target.strip().strip("<>")
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target_without_fragment = target.split("#", maxsplit=1)[0]
            if not target_without_fragment:
                continue
            resolved = (
                repo_root / target_without_fragment.lstrip("/")
                if target_without_fragment.startswith("/")
                else path.parent / target_without_fragment
            )
            if not resolved.resolve().exists():
                broken.append(f"{relative_path}:{target}")
    return _check(
        "FDC-12-local-links",
        not broken,
        "all local links in role-bearing documents resolve"
        if not broken
        else f"broken local links: {sorted(broken)}",
    )


def _input_manifest_check(
    repo_root: Path, policy_path: Path, input_manifest: dict[str, object]
) -> dict[str, str]:
    document_hashes = input_manifest.get("checked_document_sha256")
    document_hash_map = document_hashes if isinstance(document_hashes, dict) else {}
    source_hashes = input_manifest.get("checked_source_sha256")
    source_hash_map = source_hashes if isinstance(source_hashes, dict) else {}
    digest_values = [
        input_manifest.get("policy_sha256"),
        input_manifest.get("release_receipt_sha256"),
        input_manifest.get("candidate_diff_sha256"),
        input_manifest.get("verifier_sha256"),
        *document_hash_map.values(),
        *source_hash_map.values(),
    ]
    expected_keys = {
        "candidate_base_head",
        "candidate_diff_sha256",
        "checked_document_sha256",
        "checked_source_sha256",
        "current_head",
        "policy_sha256",
        "release_receipt_sha256",
        "verifier_sha256",
        "worktree_matches_index",
    }
    candidate_digest = input_manifest.get("candidate_diff_sha256")
    verifier_path = _repo_file(repo_root, VERIFIER_PATH)
    valid = (
        set(input_manifest) == expected_keys
        and _repo_file(repo_root, DEFAULT_POLICY_PATH) == policy_path.resolve()
        and input_manifest.get("candidate_base_head") == EXPECTED_CANDIDATE_BASE_HEAD
        and re.fullmatch(r"[0-9a-f]{40}", str(input_manifest.get("current_head"))) is not None
        and candidate_digest != EMPTY_SHA256
        and set(document_hash_map) == set(BOUND_DOCUMENT_PATHS)
        and set(source_hash_map) == set(BOUND_SOURCE_PATHS)
        and input_manifest.get("worktree_matches_index") is True
        and verifier_path is not None
        and verifier_path == Path(__file__).resolve()
        and input_manifest.get("verifier_sha256") == _sha256_file(verifier_path)
        and all(
            type(value) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None
            for value in digest_values
        )
    )
    return _check(
        "FDC-13-input-manifest",
        valid,
        "gate inputs and frozen staged diff are exact-hash-bound to one Git identity",
    )


def evaluate(repo_root: Path, policy_path: Path) -> dict[str, Any]:
    """Return a deterministic, authority-negative consistency report."""
    try:
        policy = _load_json(policy_path)
    except ValueError as exc:
        policy = {}
        load_check = _check("FDC-00-policy-load", False, str(exc))
    else:
        load_check = _check("FDC-00-policy-load", True, "ownership policy is valid JSON object")

    document_hashes = _document_hashes(repo_root)
    source_hashes = _source_hashes(repo_root)
    current_state = policy.get("current_state")
    current_state_map = current_state if isinstance(current_state, dict) else {}
    release_truth_path = current_state_map.get("release_truth_path")
    release_path = (
        _repo_file(repo_root, release_truth_path) if isinstance(release_truth_path, str) else None
    )
    release_receipt_sha256 = _sha256_file(release_path) if release_path is not None else None
    default_policy_path = _repo_file(repo_root, DEFAULT_POLICY_PATH)
    candidate_diff_sha256 = _git_candidate_diff_sha256(
        repo_root,
        EXPECTED_CANDIDATE_BASE_HEAD,
    )
    input_manifest: dict[str, object] = {
        "candidate_base_head": EXPECTED_CANDIDATE_BASE_HEAD,
        "candidate_diff_sha256": candidate_diff_sha256,
        "checked_document_sha256": document_hashes,
        "checked_source_sha256": source_hashes,
        "current_head": _git_head(repo_root),
        "policy_sha256": (
            _sha256_file(default_policy_path)
            if default_policy_path is not None and policy_path.resolve() == default_policy_path
            else None
        ),
        "release_receipt_sha256": release_receipt_sha256,
        "verifier_sha256": _sha256_file(Path(__file__)),
        "worktree_matches_index": _git_worktree_matches_index(repo_root),
    }
    participant_map = _participant_map(policy)
    checks = [
        load_check,
        *_metadata_checks(policy),
        _identity_check(participant_map),
        _srl_check(participant_map),
        _dual_check(participant_map),
        _native_domain_check(participant_map),
        _crosslab_check(participant_map),
        _wire_check(policy),
        _current_truth_check(repo_root, policy),
        _entrypoint_check(repo_root),
        _document_binding_check(policy, document_hashes),
        _local_link_check(repo_root),
        _input_manifest_check(repo_root, policy_path, input_manifest),
        _source_binding_check(policy, source_hashes),
        _documentation_closure_check(repo_root, input_manifest),
        _repository_file_containment_check(repo_root, policy),
        _critical_source_semantics_check(repo_root),
        _v37_history_immutability_check(repo_root),
        _independent_review_check(repo_root, input_manifest),
    ]

    result = "PASS" if all(check["status"] == "PASS" for check in checks) else "FAIL"
    report: dict[str, Any] = {
        "schema_version": "FederationDoctrineConsistencyReceipt/v1",
        "policy_id": policy.get("policy_id"),
        "result": result,
        "input_manifest": input_manifest,
        "input_manifest_sha256": _sha256_bytes(_canonical_bytes(input_manifest)),
        "checks": checks,
        "canonical_writes": 0,
        "live_actions": 0,
        "grants_authority": False,
    }
    report["receipt_id"] = _sha256_bytes(_canonical_bytes(report))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--policy", type=Path)
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    policy_path = args.policy.resolve() if args.policy else repo_root / DEFAULT_POLICY_PATH
    report = evaluate(repo_root, policy_path)
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
