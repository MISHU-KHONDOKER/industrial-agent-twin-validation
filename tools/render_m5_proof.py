"""Turn the saved M5 terminal outputs in docs/m5_proof/ into pictures (docs/images/m5_*.png).

Real terminal output, copied from the runs as they happened; local folders shortened to
<co-pilot copy> / <M4 run 2> etc. Each one passes the leak check before it is drawn.
Same drawing and colours as the M4 proofs (tools/render_m4_proof.py).

    python tools/render_m5_proof.py
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
import leak_check  # noqa: E402
import render_m4_proof as m4  # noqa: E402
import render_walkthrough as rw  # noqa: E402

SOURCE = REPO / "docs" / "m5_proof"
OUT = REPO / "docs" / "images"

TITLES = {
    "1_scorer_fixes": "M5 - five scorer fixes, tested on the real replies",
    "2_rescore": "M5 - all saved runs re-judged with the fixed scorer",
    "3_qwen3_8b_rerun": "M5 - Qwen3 8B on the same co-pilot copy: E1 2 of 2",
}


def main():
    rw.colour = m4.colour
    terms = leak_check.private_terms()
    OUT.mkdir(parents=True, exist_ok=True)
    problems, done = [], 0
    for name, title in TITLES.items():
        path = SOURCE / f"{name}.txt"
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        found = leak_check.check_file(f"docs/m5_proof/{name}.txt", text.encode(), terms)
        if found:
            problems += found
            continue
        lines = [re.sub(r"\s+$", "", ln) for ln in text.splitlines()]
        rw.render(lines, title, OUT / f"m5_{name}.png")
        done += 1
    if problems:
        print("NOT drawn (leak check):", *problems, sep="\n  ")
        return 1
    print(f"{done} picture(s) written to docs/images/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
