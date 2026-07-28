#!/usr/bin/env python3
"""WP-B15 public conformance corpus check: run all 30 tasks, emit CorpusReceipt/v1.

Loads the thirty-task public conformance corpus under
``fixtures/conformance/corpus/`` (each task a ``task-NN-<slug>/task.json``
``TaskSpec/v1``), runs every task through the real science-lab pipeline via
``srl.planning.corpus.run_task`` (a pure evaluation against the router/planner
and the contract validators), compares each task's ``expected.outcome`` against
the outcome the pipeline actually produced, and emits a single canonical
``CorpusReceipt/v1`` JSON line to stdout. Exits 0 only if every task matches
AND the declared category coverage matches the manifest; any mismatch or
coverage drift makes the exit code non-zero so the check can gate CI
(``make corpus`` and the ``public_conformance_corpus`` job in ``contracts.yml``).

Honesty (load-bearing)
----------------------
A corpus PASS never means a scientific claim is supported. The check merely
asserts that each task's *expected admission outcome* is reproduced by the
pipeline. Because no scientific backend ships in this codebase, the honest
outcome for most tasks is ``WAIT_CAPABILITY``; the typed rejection outcomes are
the cases where the contract layer genuinely refuses the input. See
``docs/contracts/conformance-corpus.md``.

Determinism
-----------
The receipt is byte-identical across runs: it is emitted via the canonical JSON
encoder (sorted keys, compact separators, UTF-8), and the non-deterministic
``duration_ms`` per task is excluded from the receipt's ``outcomes`` block (the
receipt records only the typed expected/actual/match triple per task). Two runs
of this script produce identical stdout bytes.

The script is standard library plus the in-repo ``srl`` package. It adds
``src/`` to ``sys.path`` so it can run as
``python3 scripts/checks/wp15-corpus.py`` without a prior ``uv run``, and also
works under ``uv run`` (idempotent path insertion).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Final

# ---------------------------------------------------------------------------
# Make the in-repo srl package importable when run as a bare script.
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]  # scripts/checks/wp15-corpus.py -> repo root
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from srl.contracts import dumps  # noqa: E402  (path setup must precede import)
from srl.planning.corpus import (  # noqa: E402
    CORPUS_OUTCOMES,
    load_corpus,
    run_task,
    verdict,
)

# Receipt identity.
RECEIPT_SCHEMA: Final[str] = "CorpusReceipt/v1"

# The corpus root (the directory holding the task-NN-<slug>/ task dirs).
_CORPUS_DIR: Final[Path] = _REPO_ROOT / "fixtures" / "conformance" / "corpus"

# The expected task count (the corpus is exactly thirty tasks).
_EXPECTED_TASK_COUNT: Final[int] = 30


def _emit(receipt: dict[str, Any]) -> None:
    """Write one canonical JSON line (sorted keys, compact, UTF-8) to stdout."""
    sys.stdout.buffer.write(dumps(receipt))
    sys.stdout.buffer.flush()


def _load_manifest() -> dict[str, int]:
    """Load the declared category -> count map from the corpus manifest.

    Returns an empty dict if the manifest is absent (the coverage check is then
    skipped with a warning, rather than failing hard — the manifest is advisory
    metadata, the task.json files are the source of truth).
    """
    manifest_path = _CORPUS_DIR / "manifest.json"
    if not manifest_path.is_file():
        return {}
    raw = manifest_path.read_text(encoding="utf-8")
    doc = json.loads(raw)
    categories = doc.get("categories", {})
    if not isinstance(categories, dict):
        return {}
    return {str(k): int(v) for k, v in categories.items()}


def _category_coverage(tasks: list[Any]) -> dict[str, int]:
    """Compute the observed category -> count map from the loaded tasks."""
    counts: dict[str, int] = {}
    for task in tasks:
        counts[task.category] = counts.get(task.category, 0) + 1
    return dict(sorted(counts.items()))


def _build_receipt() -> dict[str, Any]:
    """Load the corpus, run every task, and assemble the CorpusReceipt/v1 dict."""
    tasks = load_corpus(_CORPUS_DIR)

    # Run each task and record the typed expected/actual/match triple. The
    # outcome block is intentionally minimal (no duration_ms) so the receipt is
    # byte-identical across runs (duration is wall-clock, non-deterministic).
    outcomes: dict[str, dict[str, Any]] = {}
    mismatches: list[dict[str, Any]] = []
    for task in tasks:
        outcome = run_task(task)
        v = verdict(task, outcome)
        outcomes[task.task_id] = {
            "expected": v.expected,
            "actual": v.actual,
            "match": v.match,
        }
        if not v.match:
            mismatches.append(
                {
                    "task_id": task.task_id,
                    "expected": v.expected,
                    "actual": v.actual,
                    "detail": v.detail,
                }
            )

    # Category coverage: the observed counts must match the manifest's declared
    # counts exactly (a drift means a task was added/removed/mis-categorized).
    declared = _load_manifest()
    observed = _category_coverage(tasks)
    coverage_match = (not declared) or (declared == observed)

    # Every expected outcome must be a member of the outcome enum (a task
    # carrying an unknown outcome string is a corpus failure).
    all_expected_valid = all(t.expected_outcome in CORPUS_OUTCOMES for t in tasks)

    overall = "PASS" if not mismatches and coverage_match and all_expected_valid else "FAIL"

    return {
        "schema_version": RECEIPT_SCHEMA,
        "overall": overall,
        "task_count": len(tasks),
        "outcomes": outcomes,
        "mismatches": mismatches,
        "category_coverage": {
            "declared": dict(sorted(declared.items())),
            "observed": observed,
            "match": coverage_match,
        },
        "all_expected_outcomes_in_enum": all_expected_valid,
        "evidence": {
            "expected_task_count": _EXPECTED_TASK_COUNT,
            "task_count_matches": len(tasks) == _EXPECTED_TASK_COUNT,
            "outcome_enum": sorted(CORPUS_OUTCOMES),
            "mismatch_count": len(mismatches),
        },
    }


def main() -> int:
    """Run the corpus check and emit the receipt. Non-zero exit on any failure."""
    receipt = _build_receipt()
    _emit(receipt)
    return 0 if receipt["overall"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    # Stable CWD-independent behavior.
    try:
        os.chdir(_REPO_ROOT)
    except OSError:
        pass
    raise SystemExit(main())
