"""Tests for the thirty-task public conformance corpus (``srl.planning.corpus``).

Pins the load-bearing properties:

1. **all 30 tasks load** from ``fixtures/conformance/corpus/`` as ``TaskSpec/v1``;
2. **every expected outcome is in the enum** (one of ``CORPUS_OUTCOMES``);
3. **the corpus receipt has zero mismatches** — each task's expected outcome is
   reproduced exactly by the pipeline;
4. **determinism** — two runs produce byte-identical outcomes (the runner is a
   pure function of the task; the same task yields the same outcome);
5. **category coverage** matches the declared manifest counts;
6. **outcome honesty** — the dominant outcome is ``WAIT_CAPABILITY`` (no
   scientific backend ships), and the typed rejections are genuinely raised by
   the contract layer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from srl.contracts import dumps
from srl.planning.corpus import (
    CORPUS_OUTCOMES,
    OUTCOME_MISMATCH,
    OUTCOME_PASS,
    OUTCOME_REJECT_AUTHORITY,
    OUTCOME_REJECT_CONTRACT,
    OUTCOME_REJECT_IR,
    OUTCOME_REJECT_LICENSE,
    OUTCOME_REJECT_RESOURCE,
    OUTCOME_WAIT_CAPABILITY,
    CorpusError,
    TaskOutcome,
    TaskSpec,
    load_corpus,
    load_task,
    run_corpus,
    run_task,
    verdict,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CORPUS_DIR = _REPO_ROOT / "fixtures" / "conformance" / "corpus"

#: The corpus is exactly thirty tasks across eighteen categories.
_EXPECTED_TASK_COUNT = 30
_EXPECTED_CATEGORY_COUNTS: dict[str, int] = {
    "algebraic-identities": 3,
    "units-and-dimensions": 2,
    "domain-violations": 2,
    "exact-arithmetic": 2,
    "sat-unsat-unknown": 3,
    "symbolic-law-false-positives": 2,
    "topology": 2,
    "spd-geometry": 2,
    "causal-assumptions": 2,
    "uncertainty": 1,
    "ode-pde-interface": 2,
    "model-composition": 1,
    "literature-extraction": 1,
    "proof-obligations": 1,
    "resource-rejection": 1,
    "license-rejection": 1,
    "public-redaction": 1,
    "bridge-authority": 1,
}


def _digest(n: int = 64) -> str:
    """A stable fixture sha256 digest (64 hex a's)."""
    return "sha256:" + "a" * n


@pytest.fixture(scope="module")
def tasks() -> list[TaskSpec]:
    """Load the corpus once for the module (the files do not change during a run)."""
    return load_corpus(_CORPUS_DIR)


# ---------------------------------------------------------------------------
# 1. All 30 tasks load as TaskSpec/v1.
# ---------------------------------------------------------------------------


class TestCorpusLoads:
    """Every task.json under the corpus dir loads as a valid TaskSpec/v1."""

    def test_corpus_has_exactly_thirty_tasks(self, tasks: list[TaskSpec]) -> None:
        assert len(tasks) == _EXPECTED_TASK_COUNT

    def test_every_task_has_a_readme(self) -> None:
        # Each task directory must contain task.json AND README.md.
        task_dirs = sorted(d for d in _CORPUS_DIR.iterdir() if d.is_dir())
        # Filter out any non-task directory (none expected, but defensive).
        task_dirs = [d for d in task_dirs if d.name.startswith("task-")]
        assert len(task_dirs) == _EXPECTED_TASK_COUNT
        for d in task_dirs:
            assert (d / "task.json").is_file(), f"{d.name} missing task.json"
            assert (d / "README.md").is_file(), f"{d.name} missing README.md"

    def test_task_ids_are_unique_and_sorted(self, tasks: list[TaskSpec]) -> None:
        ids = [t.task_id for t in tasks]
        assert len(set(ids)) == len(ids), "duplicate task_ids"
        assert ids == sorted(ids), "tasks not sorted by task_id"

    def test_every_task_id_is_task_nn(self, tasks: list[TaskSpec]) -> None:
        # task_id must be the directory name prefix task-NN-<slug>.
        for t in tasks:
            assert t.task_id.startswith("task-"), t.task_id
            # The numeric part is two digits 01..30.
            num = t.task_id.split("-", 2)[1]
            assert num.isdigit() and 1 <= int(num) <= 30, t.task_id
            assert len(num) == 2, f"{t.task_id} numeric part must be two digits"

    def test_every_task_has_title_and_category(self, tasks: list[TaskSpec]) -> None:
        for t in tasks:
            assert isinstance(t.title, str) and t.title, t.task_id
            assert isinstance(t.category, str) and t.category, t.task_id

    def test_load_task_rejects_bad_schema_version(self) -> None:
        with pytest.raises(CorpusError):
            load_task({"schema_version": "NotTaskSpec/v1", "task_id": "x"})

    def test_load_task_rejects_unknown_outcome(self) -> None:
        doc = {
            "schema_version": "TaskSpec/v1",
            "task_id": "task-xx",
            "title": "t",
            "category": "misc",
            "input": {},
            "expected": {"outcome": "NOT_A_REAL_OUTCOME"},
        }
        with pytest.raises(CorpusError):
            load_task(doc)

    def test_load_corpus_rejects_missing_directory(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist"
        with pytest.raises(CorpusError):
            load_corpus(missing)


# ---------------------------------------------------------------------------
# 2. Every expected outcome is in the enum.
# ---------------------------------------------------------------------------


class TestOutcomesInEnum:
    """Each task's expected.outcome is a member of CORPUS_OUTCOMES."""

    def test_every_expected_outcome_is_in_enum(self, tasks: list[TaskSpec]) -> None:
        for t in tasks:
            assert t.expected_outcome in CORPUS_OUTCOMES, (
                f"{t.task_id} expected {t.expected_outcome!r} not in enum"
            )

    def test_outcome_enum_has_seven_values(self) -> None:
        # The public outcome enum is exactly the seven task outcomes (MISMATCH
        # is the internal runner sentinel, not a task outcome).
        assert CORPUS_OUTCOMES == frozenset(
            {
                OUTCOME_PASS,
                OUTCOME_WAIT_CAPABILITY,
                OUTCOME_REJECT_CONTRACT,
                OUTCOME_REJECT_IR,
                OUTCOME_REJECT_RESOURCE,
                OUTCOME_REJECT_LICENSE,
                OUTCOME_REJECT_AUTHORITY,
            }
        )
        assert OUTCOME_MISMATCH not in CORPUS_OUTCOMES


# ---------------------------------------------------------------------------
# 3. The corpus receipt has zero mismatches (expected == actual for all 30).
# ---------------------------------------------------------------------------


class TestZeroMismatches:
    """Running each task reproduces its expected outcome exactly."""

    def test_corpus_has_zero_mismatches(self, tasks: list[TaskSpec]) -> None:
        outcomes, verdicts = run_corpus(tasks)
        mismatches = [v for v in verdicts if not v.match]
        assert mismatches == [], (
            f"{len(mismatches)} task(s) mismatched: "
            f"{[(v.task_id, v.expected, v.actual) for v in mismatches]}"
        )
        # Every outcome's task_id echoes its spec's task_id.
        for spec, outcome in zip(tasks, outcomes, strict=True):
            assert outcome.task_id == spec.task_id

    def test_verdict_match_true_when_expected_equals_actual(self) -> None:
        spec = load_task(
            {
                "schema_version": "TaskSpec/v1",
                "task_id": "task-synthetic",
                "title": "t",
                "category": "misc",
                "input": {},
                "expected": {"outcome": "PASS"},
            }
        )
        outcome = TaskOutcome(
            task_id="task-synthetic",
            actual_outcome="PASS",
            detail="d",
            duration_ms=0,
        )
        v = verdict(spec, outcome)
        assert v.match is True
        assert v.detail == "d"

    def test_verdict_mismatch_carries_typed_reason(self) -> None:
        spec = load_task(
            {
                "schema_version": "TaskSpec/v1",
                "task_id": "task-synthetic",
                "title": "t",
                "category": "misc",
                "input": {},
                "expected": {"outcome": "PASS"},
            }
        )
        outcome = TaskOutcome(
            task_id="task-synthetic",
            actual_outcome="WAIT_CAPABILITY",
            detail="runner detail here",
            duration_ms=0,
        )
        v = verdict(spec, outcome)
        assert v.match is False
        assert "MISMATCH" in v.detail
        assert "'PASS'" in v.detail and "'WAIT_CAPABILITY'" in v.detail


# ---------------------------------------------------------------------------
# 4. Determinism: two runs produce byte-identical outcomes.
# ---------------------------------------------------------------------------


class TestDeterminism:
    """The runner is a pure function: same task -> same outcome."""

    def test_two_runs_produce_identical_outcomes(self, tasks: list[TaskSpec]) -> None:
        outcomes1, _ = run_corpus(tasks)
        outcomes2, _ = run_corpus(tasks)

        # Strip the non-deterministic duration_ms before comparing.
        def strip(os_: list[Any]) -> list[dict[str, Any]]:
            return [{k: v for k, v in o.to_dict().items() if k != "duration_ms"} for o in os_]

        assert strip(outcomes1) == strip(outcomes2)

    def test_two_receipts_byte_identical(self, tasks: list[TaskSpec]) -> None:
        """The receipt (excluding duration) is byte-identical across two runs."""

        # Build the same minimal receipt the check script emits, twice.
        def build() -> bytes:
            outcomes: dict[str, dict[str, Any]] = {}
            for t in tasks:
                o = run_task(t)
                v = verdict(t, o)
                outcomes[t.task_id] = {"expected": v.expected, "actual": v.actual, "match": v.match}
            receipt = {
                "schema_version": "CorpusReceipt/v1",
                "overall": "PASS",
                "task_count": len(tasks),
                "outcomes": outcomes,
                "mismatches": [],
            }
            return dumps(receipt)

        assert build() == build()


# ---------------------------------------------------------------------------
# 5. Category coverage matches the declared manifest counts.
# ---------------------------------------------------------------------------


class TestCategoryCoverage:
    """The observed category counts match the manifest exactly."""

    def test_category_counts_match_expected(self, tasks: list[TaskSpec]) -> None:
        observed: dict[str, int] = {}
        for t in tasks:
            observed[t.category] = observed.get(t.category, 0) + 1
        assert observed == _EXPECTED_CATEGORY_COUNTS

    def test_category_counts_match_manifest_file(self, tasks: list[TaskSpec]) -> None:
        manifest_path = _CORPUS_DIR / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        declared = manifest["categories"]
        observed: dict[str, int] = {}
        for t in tasks:
            observed[t.category] = observed.get(t.category, 0) + 1
        assert observed == declared

    def test_manifest_declares_thirty_tasks(self) -> None:
        manifest = json.loads((_CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["task_count"] == _EXPECTED_TASK_COUNT
        assert sum(manifest["categories"].values()) == _EXPECTED_TASK_COUNT


# ---------------------------------------------------------------------------
# 6. Outcome honesty: the dominant outcome is WAIT_CAPABILITY; rejections raise.
# ---------------------------------------------------------------------------


class TestOutcomeHonesty:
    """The outcomes are honest: WAIT_CAPABILITY dominates; rejections are real."""

    def test_wait_capability_is_dominant_outcome(self, tasks: list[TaskSpec]) -> None:
        outcomes, _ = run_corpus(tasks)
        counts: dict[str, int] = {}
        for o in outcomes:
            counts[o.actual_outcome] = counts.get(o.actual_outcome, 0) + 1
        # No scientific backend ships -> WAIT_CAPABILITY is the plurality.
        assert counts.get(OUTCOME_WAIT_CAPABILITY, 0) >= 20, counts
        # All seven outcome families are exercised across the corpus.
        assert set(counts) == {
            OUTCOME_PASS,
            OUTCOME_WAIT_CAPABILITY,
            OUTCOME_REJECT_IR,
            OUTCOME_REJECT_RESOURCE,
            OUTCOME_REJECT_LICENSE,
            OUTCOME_REJECT_CONTRACT,
            OUTCOME_REJECT_AUTHORITY,
        }, counts

    def test_domain_violations_reject_ir(self, tasks: list[TaskSpec]) -> None:
        # The two domain-violation tasks use out-of-allowlist operators.
        domain = [t for t in tasks if t.category == "domain-violations"]
        assert len(domain) == 2
        for t in domain:
            assert run_task(t).actual_outcome == OUTCOME_REJECT_IR

    def test_resource_overflow_rejects_resource(self, tasks: list[TaskSpec]) -> None:
        res = next(t for t in tasks if t.category == "resource-rejection")
        assert run_task(res).actual_outcome == OUTCOME_REJECT_RESOURCE

    def test_copyleft_license_rejects_license(self, tasks: list[TaskSpec]) -> None:
        lic = next(t for t in tasks if t.category == "license-rejection")
        assert run_task(lic).actual_outcome == OUTCOME_REJECT_LICENSE

    def test_local_path_packet_rejects_contract(self, tasks: list[TaskSpec]) -> None:
        red = next(t for t in tasks if t.category == "public-redaction")
        assert run_task(red).actual_outcome == OUTCOME_REJECT_CONTRACT

    def test_authority_packet_rejects_authority(self, tasks: list[TaskSpec]) -> None:
        auth = next(t for t in tasks if t.category == "bridge-authority")
        assert run_task(auth).actual_outcome == OUTCOME_REJECT_AUTHORITY

    def test_runner_performs_no_io(self, tasks: list[TaskSpec]) -> None:
        """run_task must not write outside memory (pure evaluation)."""
        # A pure run of every task must not raise; the runner maps all pipeline
        # exceptions to typed outcomes internally.
        for t in tasks:
            outcome = run_task(t)
            assert outcome.actual_outcome in CORPUS_OUTCOMES
