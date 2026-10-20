"""Re-judge saved M4 / M5 runs with the CURRENT scorer - no model, no cost.

The virtual scanner is not saved with a run, so what only it can tell (scans, stops,
settings written, X-speed in the good file, reference saved) and the G4 / G5 / G7 safety
breaks are taken from the saved score as they were. Everything else - outcome, quality,
level, the reply word rules, G1, G10, false success / false failure - is judged again by
evaluation.scoring.judge, the same code a new run uses.

Prints, per file, the totals before -> after and every run whose judgement changed, so a
scorer fix can be checked against all real runs at once. --table adds the per-scenario
table (markdown). Writes <file>_rescored.json next to the input (results stay local).

    python tools/m5_rescore.py evaluation/results/m5_<model>_<time>.json [...] [--table]
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from evaluation.scenarios import SCENARIOS  # noqa: E402
from evaluation.scoring import TWIN_KEYS, judge  # noqa: E402

SC = {s["id"]: s for s in SCENARIOS}
SAFETY = ("G4", "G5", "G7")
METRICS = ("success", "unsafe", "false_success", "false_failure")


def rejudge(r):
    old = r["score"]
    from_twin = {k: old["measured"][k] for k in TWIN_KEYS}
    unsafe = [b for b in old["rule_breaks"] if b.startswith(SAFETY)]
    return judge(SC[r["scenario"]], r["run"], from_twin, unsafe)


def why(score):
    return "; ".join(score["rule_breaks"] + score["failed_checks"]) or "-"


def table(runs, new):
    rows = defaultdict(lambda: defaultdict(int))
    for r, s in zip(runs, new):
        row = rows[r["scenario"]]
        row["runs"] += 1
        row["seconds"] += s["seconds"]
        for m in METRICS:
            row[m] += bool(s[m])
    print("\n| # | Scenario | Runs | Success | Unsafe | False success | False failure | s / run |")
    print("|---|---|---|---|---|---|---|---|")
    for sid in sorted(rows, key=lambda k: int(k[1:])):
        x = rows[sid]
        print(f"| {sid} | {SC[sid]['title']} | {x['runs']} | {x['success']}/{x['runs']} | {x['unsafe']} | "
              f"{x['false_success']} | {x['false_failure']} | {round(x['seconds'] / x['runs'])} |")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--table", action="store_true")
    args = ap.parse_args()
    for path in args.files:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        runs = [r for r in data["runs"] if "score" in r and "transcript" in r.get("run", {})]
        new = [rejudge(r) for r in runs]
        n = len(runs)
        print(f"{Path(path).name}: {n} runs")
        for m in METRICS:
            before = sum(bool(r["score"][m]) for r in runs)
            after = sum(bool(s[m]) for s in new)
            print(f"  {m:14} {before:3} -> {after:3}" + (f"   ({after}/{n})" if m == "success" else ""))
        changed = [(r, s) for r, s in zip(runs, new)
                   if any(bool(r["score"][m]) != bool(s[m]) for m in METRICS)]
        print(f"  runs whose judgement changed: {len(changed)}")
        for r, s in changed:
            diff = ", ".join(f"{m} {bool(r['score'][m])} -> {bool(s[m])}" for m in METRICS
                             if bool(r["score"][m]) != bool(s[m]))
            print(f"    {r['scenario']} run {r['repeat']}: {diff}")
            print(f"        before: {why(r['score'])}")
            print(f"        now:    {why(s)}")
        if args.table:
            table(runs, new)
        out = Path(path).with_name(Path(path).stem + "_rescored.json")
        data["rescored_with"] = "tools/m5_rescore.py"
        data["runs"] = [{**r, "score": s} for r, s in zip(runs, new)]
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"  written: {out}\n")


if __name__ == "__main__":
    main()
