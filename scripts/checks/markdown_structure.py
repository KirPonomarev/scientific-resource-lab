"""Stdlib Markdown structure checker for CI.

Walks every ``*.md`` file under the repository root and enforces three
structural rules:

1. Exactly one top-level heading (H1, i.e. a line starting with ``# ``),
   excluding H1-like lines inside fenced code blocks.
2. No trailing whitespace on any line.
3. The file ends with a single trailing newline.

The report is deterministic JSON written to stdout.  A non-zero exit code means
at least one Markdown file violates the structure rules.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Maximum number of characters shown in a trailing-whitespace diagnostic.
_DETAIL_SAMPLE_LEN: int = 10


@dataclass(frozen=True)
class StructureIssue:
    file: str
    rule: str
    line: int
    detail: str


@dataclass(frozen=True)
class Report:
    scanner: str
    files_scanned: int
    issues: list[StructureIssue] = field(default_factory=list)


def _count_h1_outside_fences(lines: list[str]) -> int:
    """Return the number of H1 headings outside fenced code blocks."""
    h1_count = 0
    in_fence = False
    for line in lines:
        fence_match = re.match(r"^(\s*)```", line)
        if fence_match:
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.startswith("# "):
            h1_count += 1
    return h1_count


def _check_h1(path: Path, lines: list[str]) -> list[StructureIssue]:
    """Return H1 structure issues for a single Markdown file."""
    h1_count = _count_h1_outside_fences(lines)
    if h1_count == 0:
        return [
            StructureIssue(
                file=str(path),
                rule="missing_h1",
                line=0,
                detail="no H1 heading found",
            )
        ]
    if h1_count > 1:
        return [
            StructureIssue(
                file=str(path),
                rule="multiple_h1",
                line=0,
                detail=f"found {h1_count} H1 headings",
            )
        ]
    return []


def _check_trailing_whitespace(path: Path, lines: list[str]) -> list[StructureIssue]:
    """Return trailing-whitespace issues for a single Markdown file."""
    issues: list[StructureIssue] = []
    for line_idx, line in enumerate(lines, start=1):
        if line != line.rstrip():
            if len(line) > _DETAIL_SAMPLE_LEN:
                sample = repr(line[-_DETAIL_SAMPLE_LEN:])
            else:
                sample = repr(line)
            issues.append(
                StructureIssue(
                    file=str(path),
                    rule="trailing_whitespace",
                    line=line_idx,
                    detail=sample,
                )
            )
    return issues


def _check_final_newline(path: Path, text: str) -> list[StructureIssue]:
    """Return final-newline issue for a single Markdown file if missing."""
    if not text.endswith("\n"):
        return [
            StructureIssue(
                file=str(path),
                rule="missing_final_newline",
                line=0,
                detail="file does not end with a newline",
            )
        ]
    return []


def _check_file(path: Path) -> list[StructureIssue]:
    """Return structure issues for a single Markdown file."""
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="replace")
    except OSError as exc:
        return [
            StructureIssue(
                file=str(path),
                rule="read_error",
                line=0,
                detail=str(exc),
            )
        ]

    lines = text.splitlines()
    issues: list[StructureIssue] = []
    issues.extend(_check_h1(path, lines))
    issues.extend(_check_trailing_whitespace(path, lines))
    issues.extend(_check_final_newline(path, text))
    return issues


def scan() -> Report:
    """Scan all Markdown files for structural issues."""
    issues: list[StructureIssue] = []
    files_scanned = 0
    for path in sorted(Path.cwd().rglob("*.md")):
        if ".git" in path.parts:
            continue
        ignored_dirs = {".tmp", ".venv", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
        if any(part in ignored_dirs for part in path.parts):
            continue
        # GitHub issue/PR templates use their own required YAML frontmatter and
        # section structure; they are not ordinary project documentation.
        if ".github/ISSUE_TEMPLATE" in str(path) or path.name == "pull_request_template.md":
            continue
        files_scanned += 1
        issues.extend(_check_file(path))
    return Report(
        scanner="markdown_structure/v1",
        files_scanned=files_scanned,
        issues=issues,
    )


def main() -> int:
    """Entry point: print JSON report and exit 1 if any Markdown file is malformed."""
    report = scan()
    print(
        json.dumps(
            asdict(report),
            indent=2,
            default=str,
        )
    )
    return 1 if report.issues else 0


if __name__ == "__main__":
    sys.exit(main())
