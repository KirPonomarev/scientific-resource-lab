"""Stdlib Markdown link-domain allowlist checker for CI.

Walks every ``*.md`` file under the repository root, extracts ``https://`` URLs,
and verifies that each URL's domain is in the project allowlist.  No live
network requests are made; the check is a pure local domain test.

The allowlist is intentionally small and maps to domains that are part of the
project's public references (GitHub, SRL schemas, open-source license and
standard bodies).

The report is deterministic JSON written to stdout.  A non-zero exit code means
at least one Markdown link points outside the allowlist.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Final
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------

_ALLOWED_DOMAINS: Final[frozenset[str]] = frozenset(
    {
        "github.com",
        "schemas.srlab.dev",
        "choosealicense.com",
        "contributor-covenant.org",
        "keepachangelog.com",
        "spdx.org",
        "json-schema.org",
        "docs.github.com",
        "openmath.org",
        "qudt.org",
        "ucum.org",
        "creativecommons.org",
        "apache.org",
        "mit.edu",
        "python.org",
        "pypi.org",
        # Referenced by existing project documentation (CHANGELOG.md, CONTRIBUTING.md).
        "semver.org",
        "conventionalcommits.org",
    }
)

_URL_RE: Final[re.Pattern[str]] = re.compile(r"https?://[^\s\)\]\>\"]+")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LinkIssue:
    file: str
    line: int
    url: str
    domain: str
    reason: str


@dataclass(frozen=True)
class Report:
    scanner: str
    files_scanned: int
    links_ok: int
    issues: list[LinkIssue] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _domain_from_url(url: str) -> str | None:
    """Return the registered domain for an allowed URL, or None for malformed URLs."""
    parsed = urlparse(url)
    if not parsed.hostname:
        return None
    hostname = parsed.hostname.lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname


def _is_allowed(domain: str) -> bool:
    """Return True if *domain* or any of its parent domains is in the allowlist."""
    parts = domain.split(".")
    for idx in range(len(parts)):
        candidate = ".".join(parts[idx:])
        if candidate in _ALLOWED_DOMAINS:
            return True
    return False


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def scan() -> Report:
    """Scan all Markdown files and check their link domains."""
    issues: list[LinkIssue] = []
    files_scanned = 0
    links_ok = 0

    for path in sorted(Path.cwd().rglob("*.md")):
        if ".git" in path.parts:
            continue
        files_scanned += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            issues.append(
                LinkIssue(
                    file=str(path),
                    line=0,
                    url="",
                    domain="",
                    reason=f"read error: {exc}",
                )
            )
            continue

        for line_idx, line in enumerate(text.splitlines(), start=1):
            for match in _URL_RE.finditer(line):
                url = match.group(0)
                # Strip trailing punctuation that may have been captured.
                url = url.rstrip(".,;:!?'") if not url.endswith("/") else url
                domain = _domain_from_url(url)
                if domain is None:
                    issues.append(
                        LinkIssue(
                            file=str(path),
                            line=line_idx,
                            url=url,
                            domain="",
                            reason="malformed URL",
                        )
                    )
                elif _is_allowed(domain):
                    links_ok += 1
                else:
                    issues.append(
                        LinkIssue(
                            file=str(path),
                            line=line_idx,
                            url=url,
                            domain=domain,
                            reason="domain not in allowlist",
                        )
                    )

    return Report(
        scanner="link_check/v1",
        files_scanned=files_scanned,
        links_ok=links_ok,
        issues=issues,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    """Entry point: print JSON report and exit 1 if any link is outside the allowlist."""
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
