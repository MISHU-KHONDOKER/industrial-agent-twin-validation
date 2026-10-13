"""Turn the saved M4 terminal outputs in docs/m4_proof/ into pictures (docs/images/m4_*.png).

The texts are real terminal output, copied from the runs as they happened; local
folders are shortened to <project> / <private>. Each one passes the leak check
before it is drawn. Same look as the M3 walkthrough pictures.

    python tools/render_m4_proof.py
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import leak_check  # noqa: E402
import render_walkthrough as rw  # noqa: E402

SOURCE = REPO / "docs" / "m4_proof"
OUT = REPO / "docs" / "images"

TITLES = {
    "1_first_real_run": "M4 - first real run: 6 conversations with the real model (before the fixes)",
    "2_twin_result_file": "M4 fix 1 - the virtual scanner writes the result file like the real one",
    "3_scoring_check": "M4 fix 2 - the scorer judges good and deliberately bad runs (no model, no cost)",
    "4_second_real_run": "M4 - the same 6 conversations again, after the fixes",
    "5_f29_fix": "F29 fixed - no scan with a slide the customer did not name (guard on / off / on)",
    "6_f30_fix": "F30 fixed - a customer never sees a support code the co-pilot does not have",
    "7_reach_check": "M4 - 14 scenarios: every machine end state reachable (stand-in model, no cost)",
    "8_new_scenarios_real_run": "M4 - the 11 new scenarios with the real model: 22 conversations",
    "9_official_run": "M4 - first official measurement: 14 scenarios x 10 = 140 conversations",
    "10_scorer_fix": "M4 - scorer fix: tested, re-checked on all 140",
    "11_f37_fix": "F37 fixed - the customer is always told which settings were corrected (check on / off / on)",
    "12_official_run_2": "M4 - second official measurement (test copy with F37): 139 of 140",
    "13_twin_same_version": "M4 - the twin side: E1, E11, E12 x 3 with the version tested on the real scanner",
    "14_real_scanner": "M4 - the real scanner: recorded Customer conversations scored by the same rules",
    "15_scorer_e1_fix": "M4 - scorer fix for a real reply ('Your slide is done'): tested, re-checked on all 280",
}

m3_colour = rw.colour                            # kept before main() swaps it for colour()


def colour(line):
    s = line.lstrip()
    if re.match(r"E\d+\s+\w{8} \d{8}.*\bPASS\b", s):          # a recorded real conversation
        return (90, 220, 120), True
    if re.match(r"E\d+\s+\w{8} \d{8}.*\bFAIL\b", s):
        return (255, 110, 110), True
    if re.match(r"E\d+ #\d+: SUCCESS FALSE_FAILURE", s):
        return (255, 200, 80), True
    if re.match(r"E\d+ #\d+: SUCCESS", s) or re.match(r"E\d+: (\d+)/\1 SUCCESS", s):
        return (90, 220, 120), True
    if re.match(r"E\d+: \d+/\d+ SUCCESS", s):
        return (255, 200, 80), True
    if s.endswith("PASSED"):
        return (90, 220, 120), False
    if s.endswith("FAILED"):
        return (255, 110, 110), True
    if re.match(r"E\d+ run \d+:", s):
        return (255, 200, 80), False
    if s.startswith(("success ", "false failure ", "runs whose judgement")) or "passed in" in s:
        return (230, 230, 230), True
    if re.match(r"E\d+ #\d+: FAIL", s):
        return (255, 110, 110), True
    if s.startswith("why:"):
        return (255, 200, 80), False
    if s.startswith("REACHABLE"):
        return (90, 220, 120), False
    if s.startswith("PROBLEM"):
        return (255, 110, 110), True
    if s.startswith(("TOTAL:", "scorer judged")) or s.endswith("scenarios reachable"):
        return (230, 230, 230), True
    if s.startswith("model calls") and " FAIL" in s:
        return (255, 110, 110), True
    if s.startswith(("F29 fix PROVEN", "F30 fix PROVEN", "F37 fix PROVEN")) or re.match(r"\d\. (guard|check) ON", s):
        return (90, 220, 120), True
    if re.match(r"\d\. (guard|check) OFF", s) or s.startswith("model calls") and "G1 BROKEN" in s:
        return (255, 110, 110), True
    return m3_colour(line)


def main():
    rw.colour = colour                           # the M3 drawing code, M4 colours
    terms = leak_check.private_terms()
    OUT.mkdir(parents=True, exist_ok=True)
    problems, done = [], 0
    for name, title in TITLES.items():
        path = SOURCE / f"{name}.txt"
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        found = leak_check.check_file(f"docs/m4_proof/{name}.txt", text.encode(), terms)
        if found:
            problems += found
            continue
        lines = [re.sub(r"\s+$", "", ln) for ln in text.splitlines()]
        rw.render(lines, title, OUT / f"m4_{name}.png")
        done += 1
    if problems:
        print("NOT drawn (leak check):", *problems, sep="\n  ")
        return 1
    print(f"{done} picture(s) written to docs/images/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
