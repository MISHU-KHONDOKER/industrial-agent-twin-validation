"""F37 fix demo: a customer is always told which scanner settings were corrected.

F37 (found by the first official M4 run, E4 #5): four wrong settings were corrected
before the scan, but the answer only said "Your slide has been scanned" - the customer
never learned what was changed. The fix is a check in the co-pilot's code: in Customer
mode every corrected setting of this turn must be in the answer, by name and new value;
whatever the model left out is put in front of the answer, built from the tool result
(no extra model call).

A stand-in model says what the real model said. Four runs:

  1. check ON,  model leaves the settings out (E4 #5)  -> the settings reach the customer
  2. check OFF  (in memory, no file is changed)        -> the old defect: nothing told
  3. check ON,  model lists them itself (E4 #1)         -> the answer stays as it is
  4. check ON,  no setting was changed (E1)            -> the answer stays as it is

Run with the PRIVATE project's Python, against the co-pilot that has the fix:

    <private>/venv/Scripts/python tools/demo_f37_fix.py <co-pilot folder>
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
PRIVATE = sys.argv[1] if len(sys.argv) > 1 else str(REPO.parent)

from openai.types.chat import ChatCompletion  # noqa: E402

import evaluation.driver as driver  # noqa: E402
from evaluation.scenarios import SCENARIOS  # noqa: E402
from evaluation.scoring import score_run  # noqa: E402

SC = {s["id"]: s for s in SCENARIOS}
LEFT_OUT = "Your slide has been scanned. Does this scan look right to you?"            # E4 #5
LISTED = ("Some scanner settings were wrong, so I corrected them before scanning:\n\n"     # E4 #1
          "- Anti-Blur: 50 → 10\n- Focus Density: 0 → 4\n- Stitch Mode: 0 → 2\n"
          "- [Slide] Type: Generic → TCT\n\nYour slide has been scanned. Does this scan look right to you?")


def completion(content=None, tool=None, args=None):
    msg = {"role": "assistant", "content": content}
    if tool:
        msg["tool_calls"] = [{"id": "c1", "type": "function",
                              "function": {"name": tool, "arguments": json.dumps(args)}}]
    return ChatCompletion.model_validate({
        "id": "x", "object": "chat.completion", "created": 0, "model": "stand-in",
        "choices": [{"index": 0, "finish_reason": "stop", "message": msg}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})


def stand_in(final):
    it = iter([completion("Hello."), completion("Which slide should I scan — 1, 2, 3 or 4?"),
               completion(tool="auto_scan", args={"slide": 1}), completion(final)])
    return lambda *a, **k: next(it)


def run(step, label, sid, final, check=True):
    load = driver.load_copilot

    def load_with_or_without_check(private_root, twin):
        main = load(private_root, twin)
        if not hasattr(main, "_settings_not_told"):
            raise SystemExit(f"{private_root}: this co-pilot has no F37 check")
        if not check:
            main._settings_not_told = lambda *a, **k: []          # the check switched off
        return main

    driver.load_copilot = load_with_or_without_check
    try:
        r = driver.run_conversation(PRIVATE, SC[sid]["script"], SC[sid]["mode"],
                                    faults=SC[sid]["faults"], fake_model=stand_in(final))
    finally:
        driver.load_copilot = load
    seen = r["transcript"][-1]["text"]
    s = score_run(SC[sid], r)
    print(f"{step}. check {'ON ' if check else 'OFF'}  {label}")
    for line in seen.splitlines():
        if line.strip():
            print(f"     customer sees: {line}")
    print(f"     model calls: {len(r['model_calls'])}  ->  {sid} {'SUCCESS' if s['success'] else 'FAIL'}"
          f"{'  | ' + '; '.join(s['failed_checks']) if s['failed_checks'] else ''}")
    return s["success"], seen


if __name__ == "__main__":
    a, _ = run(1, "(model leaves the corrected settings out, as in E4 #5)", "E4", LEFT_OUT)
    b, _ = run(2, "(model leaves the corrected settings out)", "E4", LEFT_OUT, check=False)
    c, c_seen = run(3, "(model lists the settings itself, as in E4 #1)", "E4", LISTED)
    d, d_seen = run(4, "(no setting was changed)", "E1", "Your slide has been scanned.")
    ok = a and not b and c and c_seen == LISTED and d and d_seen == "Your slide has been scanned."
    print(f"\nF37 fix {'PROVEN' if ok else 'NOT proven'}: corrected settings reach the customer even when "
          f"the model leaves them out; an answer that already has them, or a scan without changes, stays as it is")
    sys.exit(0 if ok else 1)
