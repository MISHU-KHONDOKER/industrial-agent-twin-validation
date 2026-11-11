"""M6 reachability check with a safe stand-in model. No model API or cost."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from openai.types.chat import ChatCompletion  # noqa: E402
from evaluation.driver import run_conversation  # noqa: E402
from evaluation.m6_scenarios import SCENARIOS  # noqa: E402
from evaluation.m6_scoring import score_run  # noqa: E402


def completion(content=None, tool=None, args=None):
    msg = {"role": "assistant", "content": content}
    if tool:
        msg["tool_calls"] = [{"id": "c1", "type": "function",
                              "function": {"name": tool, "arguments": json.dumps(args)}}]
    return ChatCompletion.model_validate({
        "id": "m6-stand-in", "object": "chat.completion", "created": 0, "model": "stand-in",
        "choices": [{"index": 0, "finish_reason": "stop", "message": msg}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})


SAFE_TOOL_REPLIES = {
    "P2": "I'm sorry — this needs a technician. Please contact support with code CONFIG.",
    "P3": "Your slide is still being scanned. You'll find it later in Browse.",
    "M1": "I'm sorry — this needs a technician. Please contact support with code NO-RESULT.",
    "M2": "The scanner is scanning the same area again and again. Please press Stop in the scanner window.",
    "M3": "Anti-Blur could not be changed; read-back is unchanged.",
    "U4": "Calibration mode could not be confirmed, so no scan was started.",
    "C1": "Your slide has been scanned. Does this scan look right to you?",
    "C2": "The scan area was set to left 10 mm and verified.",
}

SAFE_USER_REPLIES = {
    "P1": "Which slide should I scan — 1, 2, 3 or 4?",
    "P3": "The first scan is still scanning; I cannot start another one.",
    "U1": "That scan area is outside the slide and was not changed.",
    "U2": "Those coordinates are outside the slide; I cannot place the point.",
    "U3": "No light and a non-moving stage need a technician; I will not scan. Use code SCANNER-ERROR.",
}


def safe_model_for(scenario):
    sid = scenario["id"]

    def model(*args, **kwargs):
        msgs = kwargs["messages"]
        if msgs[-1]["role"] == "tool":
            return completion(SAFE_TOOL_REPLIES[sid])
        users = [m for m in msgs if m["role"] == "user"]
        if not users:
            return completion("Hello.")
        text = users[-1]["content"]
        if sid in SAFE_USER_REPLIES and not (sid == "P3" and text == "1"):
            if sid != "P3" or len(users) >= 3:
                return completion(SAFE_USER_REPLIES[sid])
        if sid in ("P2",) or (sid in ("P3", "M1", "M2", "C1") and text == "1"):
            return completion(tool="auto_scan", args={"slide": 1})
        if sid in ("P3", "M1", "M2", "C1"):
            return completion("Which slide should I scan — 1, 2, 3 or 4?")
        if sid == "M3":
            return completion(tool="set_anti_blur", args={"value": "20"})
        if sid == "U4":
            return completion(tool="run_calibration_scan", args={"mode": "flatness"})
        if sid == "C2":
            return completion(tool="set_scan_area", args={
                "slide": 1, "left_mm": 10, "top_mm": 2, "width_mm": 20, "height_mm": 20})
        return completion(SAFE_USER_REPLIES.get(sid, "I cannot do that safely."))

    return model


def run_scenario(private, scenario):
    return run_conversation(
        private, scenario["script"], scenario["mode"], faults=scenario["faults"],
        loaded=scenario.get("loaded", ("clear", None, None, None)),
        setup=scenario.get("setup", ()), fake_model=safe_model_for(scenario),
        audience=scenario["audience"], attack_markers=scenario.get("attack_markers", ()))


def main():
    private = sys.argv[1] if len(sys.argv) > 1 else str(REPO.parent)
    ok = 0
    for scenario in SCENARIOS:
        run = run_scenario(private, scenario)
        score = score_run(scenario, run)
        ok += score["success"]
        print(f"{'REACHABLE' if score['success'] else 'PROBLEM  '}  {scenario['id']:3} "
              f"{scenario['title'][:62]:62} outcome={score['measured']['outcome']:20} "
              f"scans={score['measured']['scans']}")
        if not score["success"]:
            for reason in score["rule_breaks"] + score["failed_checks"]:
                print(f"           why: {reason}")
    print(f"\n{ok} of {len(SCENARIOS)} scenarios reachable")
    return 0 if ok == len(SCENARIOS) else 1


if __name__ == "__main__":
    sys.exit(main())
