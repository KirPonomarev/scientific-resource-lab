"""Placeholder for the public demo build check.

WP-F52 will introduce the public demo build and deployment verification.  For
WP-A04 the job only records that the placeholder is active and exits cleanly
so the docs workflow can be registered in the branch protection ruleset.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    """Print a placeholder note and exit 0."""
    print(
        json.dumps(
            {
                "scanner": "demo_placeholder/v1",
                "note": "Public demo build and deploy verification arrive in WP-F52.",
                "status": "skipped",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
