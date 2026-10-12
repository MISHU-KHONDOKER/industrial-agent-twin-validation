"""Re-check a saved M4 run with the CURRENT reply rules - no model, no cost.

Only the parts that depend on the customer's words are re-checked (the scenario's
reply word rules and the false-failure claim). Everything measured on the virtual
scanner (scans, settings written, safety rules) is taken from the saved score as it
was. Prints every run whose judgement changes, so a scorer fix can be checked against
all real replies at once: a fix is only accepted if it changes exactly the runs it was
meant for.

    python tools/m4_rescore_replies.py evaluation/results/m4_<time>.json
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from evaluation.scenarios import SCENARIOS  # noqa: E402
from evaluation.scoring import claims_failure, reply_failures  # noqa: E402

EXPECT = {s["id"]: s["expect"] for s in SCENARIOS}


def main(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    changed, old_ok, new_ok, old_ff, new_ff = [], 0, 0, 0, 0
    for r in data["runs"]:
        s, sid = r["score"], r["scenario"]
        replies = "\n".join(t["text"] for t in r["run"]["transcript"][1:] if t["role"] == "copilot")
        other = [f for f in s["failed_checks"] if not f.startswith(("reply lacks", "reply contains"))]
        failed = other + reply_failures(EXPECT[sid], replies)
        success = not failed and not s["rule_breaks"]
        expected_code = EXPECT[sid].get("outcome") not in (None, "OK")
        false_failure = claims_failure(replies) and s["measured"]["outcome"] == "OK" and not expected_code
        old_ok += s["success"]; new_ok += success
        old_ff += s["false_failure"]; new_ff += false_failure
        if success != s["success"] or false_failure != s["false_failure"]:
            changed.append(f"{sid} run {r['repeat']}: success {s['success']} -> {success}, "
                           f"false failure {s['false_failure']} -> {false_failure}")
    n = len(data["runs"])
    print(f"{path}: {n} runs")
    print(f"  success        {old_ok}/{n} -> {new_ok}/{n}")
    print(f"  false failure  {old_ff} -> {new_ff}")
    print(f"  runs whose judgement changed: {len(changed)}")
    for line in changed:
        print("   ", line)


if __name__ == "__main__":
    main(sys.argv[1])
