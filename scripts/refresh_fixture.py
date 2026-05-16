#!/usr/bin/env python3
"""Re-download the three OEB feeds and diff against the committed fixtures.

Run before each release to catch schema drift early:

    python scripts/refresh_fixture.py

This script does NOT modify the committed fixtures; it downloads each live
feed to ``tests/fixtures/_live_<name>`` and prints a diff against the
matching committed fixture. Review the diffs manually -- if the schema
changed, update the fixture and the parser accordingly.

Exit code is non-zero if ANY feed diff is non-empty.
"""

from __future__ import annotations

import difflib
import sys
import urllib.request
from pathlib import Path

FEEDS = {
    "bill_data.xml": "https://www.oeb.ca/_html/calculator/data/BillData.xml",
    "bill_data_gs.xml": "https://www.oeb.ca/_html/calculator/data/BillData_GS.xml",
    "gas_bill_data.xml": "https://www.oeb.ca/_html/calculator/data/GasBillData.xml",
}


def _diff_one(fixtures: Path, name: str, url: str) -> int:
    live = fixtures / f"_live_{name}"
    committed = fixtures / name
    print(f"Downloading {url}...")
    with urllib.request.urlopen(url, timeout=60) as resp:
        body = resp.read().decode("utf-8")
    live.write_text(body, encoding="utf-8")
    print(f"  -> wrote {live} ({len(body)} bytes)")

    if not committed.exists():
        print(f"No committed fixture at {committed}; nothing to diff.")
        return 0

    a = committed.read_text(encoding="utf-8").splitlines()
    b = body.splitlines()
    diff = list(
        difflib.unified_diff(
            a, b, fromfile=str(committed), tofile=str(live), lineterm=""
        )
    )
    if not diff:
        print(f"No diff against {name}.")
        return 0

    print(f"\n--- Diff for {name} (committed -> live) ---")
    for line in diff:
        print(line)
    return 1


def main() -> int:
    fixtures = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
    exit_code = 0
    for name, url in FEEDS.items():
        exit_code |= _diff_one(fixtures, name, url)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
