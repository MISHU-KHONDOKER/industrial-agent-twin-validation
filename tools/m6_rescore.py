"""Re-judge saved M6 runs with the current scorer; no model calls or cost."""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from evaluation.m6_scenarios import BY_ID, SCENARIOS  # noqa: E402
from evaluation.m6_scoring import aggregate, judge  # noqa: E402
from m6_run import write_report  # noqa: E402

METRICS = ("valid", "success", "refused_or_clarified", "attack_success", "unsafe",
           "false_success", "false_failure", "invented_code", "correct_escalation")


def regenerate_report(data, report, official=False):
    by_scenario, families = [], defaultdict(list)
    for scenario in SCENARIOS:
        scores = [r["score"] for r in data["runs"] if r["scenario"] == scenario["id"]]
        if scores:
            by_scenario.append((scenario, aggregate(scores)))
            families[scenario["family"]] += scores
    by_family = [(family, aggregate(scores)) for family, scores in families.items()]
    return write_report(by_scenario, by_family, data["total"], data["repeats"], data["started"],
                        report, official, data.get("original_total"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--report", help="regenerate a report; requires exactly one input file")
    ap.add_argument("--official", action="store_true", help="label the regenerated report official")
    args = ap.parse_args()
    if args.report and len(args.files) != 1:
        ap.error("--report requires exactly one input file")
    for filename in args.files:
        path = Path(filename)
        data = json.loads(path.read_text(encoding="utf-8"))
        runs = [r for r in data["runs"] if "score" in r and "twin_state" in r["score"]]
        new = [judge(BY_ID[r["scenario"]], r["run"], r["score"]["twin_state"]) for r in runs]
        print(f"{path.name}: {len(runs)} runs")
        for metric in ("success", "attack_success", "unsafe", "false_success", "invented_code"):
            before = sum(bool(r["score"][metric]) for r in runs)
            after = sum(bool(s[metric]) for s in new)
            print(f"  {metric:16} {before:3} -> {after:3}")
        changed = [(r, s) for r, s in zip(runs, new)
                   if any(r["score"][m] != s[m] for m in METRICS)]
        print(f"  runs whose judgement changed: {len(changed)}")
        for r, score in changed:
            diff = ", ".join(f"{m} {r['score'][m]!r} -> {score[m]!r}" for m in METRICS
                             if r["score"][m] != score[m])
            print(f"    {r['scenario']} run {r['repeat']}: {diff}")
            print(f"        before: {'; '.join(r['score']['rule_breaks'] + r['score']['failed_checks']) or '-'}")
            print(f"        now:    {'; '.join(score['rule_breaks'] + score['failed_checks']) or '-'}")
        data["original_total"] = data.get("original_total", data["total"])
        data["total"] = aggregate(new)
        data["rescored_with"] = "tools/m6_rescore.py"
        data["runs"] = [{**r, "score": s} for r, s in zip(runs, new)]
        out = path.with_name(path.stem + "_rescored.json")
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        print(f"  written: {out}\n")
        if args.report and not regenerate_report(data, args.report, args.official):
            return 1


if __name__ == "__main__":
    main()
