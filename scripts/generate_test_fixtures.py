"""Write the programmatic image fixtures to disk for manual detector debugging.

Usage:
    python scripts/generate_test_fixtures.py
    python scripts/generate_test_fixtures.py --output C:/tmp/calendars
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from tests.fixtures import build_synthetic_calendar


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "tests" / "fixtures" / "generated",
        help="directory for generated PNG files",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    cases = {
        "github-light.png": {"theme": "light", "scale": 1.0},
        "github-light-half.png": {"theme": "light", "scale": 0.5},
        "github-light-double.png": {"theme": "light", "scale": 2.0},
        "github-dark.png": {"theme": "dark", "scale": 1.0},
        "halloween-non-green.png": {"theme": "halloween", "scale": 1.0},
        "partial-first-and-last-week.png": {
            "theme": "light",
            "scale": 1.0,
            "partial_weeks": True,
        },
    }
    for filename, options in cases.items():
        calendar = build_synthetic_calendar(**options)
        calendar.save(args.output / filename)
        print(f"wrote {args.output / filename}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
