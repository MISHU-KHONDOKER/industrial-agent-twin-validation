"""Prove M7 traces explain normal and failed runs. No model API or cost."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from evaluation.driver import run_conversation  # noqa: E402
from evaluation.m6_scenarios import BY_ID  # noqa: E402
from evaluation.m6_scoring import score_run  # noqa: E402
from evaluation.tracing import read_trace, validate_trace  # noqa: E402
from m6_reach_check import SAFE_TOOL_REPLIES, completion, safe_model_for  # noqa: E402


def unsafe_rescan_model(*args, **kwargs):
    messages = kwargs["messages"]
    if messages[-1]["role"] == "tool":
        return completion(SAFE_TOOL_REPLIES["P3"])
    users = [message for message in messages if message["role"] == "user"]
    if not users:
        return completion("Hello.")
    if users[-1]["content"] == "start scan":
        return completion("Which slide should I scan — 1, 2, 3 or 4?")
    return completion(tool="auto_scan", args={"slide": 1})


def missing_code_model(*args, **kwargs):
    users = [message for message in kwargs["messages"] if message["role"] == "user"]
    if not users:
        return completion("Hello.")
    return completion("I will not scan. This needs a technician.")


def failing_model(*args, **kwargs):
    users = [message for message in kwargs["messages"] if message["role"] == "user"]
    if users:
        raise RuntimeError("deliberate M7 model failure")
    return completion("Hello.")


def run_case(private, scenario_id, model=None, faults=None):
    scenario = BY_ID[scenario_id]
    run = run_conversation(
        private, scenario["script"], scenario["mode"],
        faults=scenario["faults"] if faults is None else faults,
        loaded=scenario.get("loaded", ("clear", None, None, None)),
        setup=scenario.get("setup", ()),
        fake_model=model or safe_model_for(scenario), audience=scenario["audience"],
        attack_markers=scenario.get("attack_markers", ()),
    )
    score = score_run(scenario, run)
    run["trace"].scored(score, scenario_id)
    return run, score, read_trace(run["trace_path"])


def has_complete_chain(events):
    machine_requests = {event["request_id"] for event in events if event["event"] == "machine_action"}
    for request_id in machine_requests:
        kinds = {event["event"] for event in events if event.get("request_id") == request_id}
        if not {"chat_started", "model_completed", "tool_completed", "machine_action",
                "chat_completed"} <= kinds:
            return False
    return bool(machine_requests) and any(event["event"] == "evaluation_scored" for event in events)


def behavior_snapshot(run):
    return {
        "transcript": run["transcript"],
        "model_calls": [{key: value for key, value in call.items() if key != "seconds"}
                        for call in run["model_calls"]],
        "tool_calls": [{key: value for key, value in call.items() if key != "seconds"}
                       for call in run["tool_calls"]],
        "machine_actions": [(door, action) for door, action, _ in run["twin"].log],
        "live_values": dict(run["twin"].live),
        "scan_region": run["twin"].scan_region_mm,
        "error": run["error"],
    }


def tracing_is_behavior_neutral(private):
    scenario = BY_ID["C1"]
    kwargs = dict(mode=scenario["mode"], faults=scenario["faults"],
                  loaded=scenario.get("loaded", ("clear", None, None, None)),
                  setup=scenario.get("setup", ()), audience=scenario["audience"])
    baseline = run_conversation(private, scenario["script"], fake_model=safe_model_for(scenario),
                                trace_dir=False, **kwargs)
    traced = run_conversation(private, scenario["script"], fake_model=safe_model_for(scenario),
                              **kwargs)
    return behavior_snapshot(baseline) == behavior_snapshot(traced)


def main():
    private = sys.argv[1] if len(sys.argv) > 1 else str(REPO.parent)
    cases = [
        ("normal scan", "C1", None, None,
         lambda run, score, events: score["success"] and has_complete_chain(events)),
        ("unsafe second scan", "P3", unsafe_rescan_model, None,
         lambda run, score, events: score["unsafe"] and sum(
             event["event"] == "machine_action" and event.get("action") == "StartScan"
             for event in events) >= 2),
        ("missing escalation code", "U3", missing_code_model, None,
         lambda run, score, events: not score["success"] and score["correct_escalation"] is False
         and any(event["event"] == "evaluation_scored" and event.get("correct_escalation") is False
                 for event in events)),
        ("recovered model exception", "C1", failing_model, None,
         lambda run, score, events: any(event["event"] == "model_failed" for event in events)
         and any(event["event"] == "chat_completed" and event.get("turn") == 1
                 for event in events)),
        ("tool failure", "C1", None, ["other_machine_good_file"],
         lambda run, score, events: not score["success"] and any(
             event["event"] == "tool_completed" and event.get("ok") is False
             and event.get("support_code") == "CONFIG" for event in events)),
    ]
    passed = 0
    for name, scenario_id, model, faults, explained in cases:
        run, score, events = run_case(private, scenario_id, model, faults)
        problems = validate_trace(run["trace_path"])
        valid_explained = not problems and explained(run, score, events)
        passed += valid_explained
        print(f"{'PASS' if valid_explained else 'FAIL'}  {name}: {len(events)} events")
        print(f"      trace: {run['trace_path']}")
        for problem in problems:
            print(f"      invalid: {problem}")
        if not problems and not valid_explained:
            print(f"      score: {score['failed_checks'] + score['rule_breaks']}")
    behavior_neutral = tracing_is_behavior_neutral(private)
    print(f"{'PASS' if behavior_neutral else 'FAIL'}  tracing on/off behavior is identical")
    print(f"\n{passed} of {len(cases)} traces valid and explanatory; "
          f"behavior-neutral={behavior_neutral}")
    return 0 if passed == len(cases) and behavior_neutral else 1


if __name__ == "__main__":
    sys.exit(main())
