#!/usr/bin/env python3
"""Run the scanner on every fixture in tests/fixtures and compare the finding IDs with
that fixture's expected.txt. Missing IDs are missed violations; extra IDs are false alarms.

  python3 tests/run_tests.py
"""
import re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCAN = HERE.parent / "scripts" / "scan.py"
ENV_DEPENDENT = {"XCODE-OLD"}  # depends on the machine running the tests


def main():
    failed = 0
    for fx in sorted((HERE / "fixtures").iterdir()):
        exp_file = fx / "expected.txt"
        if not exp_file.exists():
            continue
        expected = {l.strip() for l in exp_file.read_text().splitlines() if l.strip() and not l.startswith("#")}
        out = subprocess.run([sys.executable, str(SCAN), str(fx), "--no-store"],
                             capture_output=True, text=True, check=True).stdout
        got = set(re.findall(r"^### (\S+) ·", out, re.M)) - ENV_DEPENDENT
        missing, extra = expected - got, got - expected
        if missing or extra:
            failed += 1
            print(f"FAIL {fx.name}")
            for i in sorted(missing):
                print(f"  missed:      {i}")
            for i in sorted(extra):
                print(f"  false alarm: {i}")
        else:
            print(f"ok   {fx.name} ({len(got)} findings)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
