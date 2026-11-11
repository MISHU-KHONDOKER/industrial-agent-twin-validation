"""M7 tracing: correlation, failure evidence, privacy, and validation."""
import threading

import pytest

from evaluation.tracing import (Trace, format_trace, read_trace, validate_events,
                                validate_trace)


def events_of(events, kind):
    return [event for event in events if event["event"] == kind]


def test_chat_model_tool_machine_and_score_share_one_request(tmp_path):
    trace = Trace(tmp_path)
    with trace.request(1, session_id="session", mode="brightfield", audience="customer") as request:
        with trace.model_call("fake") as model:
            model.complete(prompt_tokens=10, completion_tokens=2, cached_tokens=8,
                           asked_for_tools=["auto_scan"])
        trace.tool_requested("auto_scan", "provider-call", {
            "slide": 1, "api_key": "must-not-appear", "path": "D:\\private\\scanner",
        })
        with trace.tool_call("auto_scan", {"slide": 1, "api_key": "must-not-appear"}) as tool:
            trace.machine_events([("socket", "StartScan", {
                "slide_no": 0, "sample_id": "must-not-appear", "box": [1.0, 2.0, 3.0, 4.0],
            })])
            tool.complete(ok=True, support_code=None, still_scanning=False)
        request.complete(reply_returned=True)
    trace.scored({"success": True, "unsafe": False, "false_success": False,
                  "false_failure": False, "failed_checks": [], "rule_breaks": []}, "C1", 1)
    trace.run_completed()

    events = read_trace(trace.path)
    assert validate_trace(trace.path) == []
    request_id = events_of(events, "chat_started")[0]["request_id"]
    correlated = events_of(events, "model_started") + events_of(events, "tool_started")
    correlated += events_of(events, "machine_action")
    assert {event["request_id"] for event in correlated} == {request_id}
    assert events_of(events, "tool_requested")[0]["arguments"] == {"slide": 1}
    assert events_of(events, "tool_started")[0]["arguments"] == {"slide": 1}
    assert events_of(events, "machine_action")[0]["detail"] == {
        "slide_no": 0, "box": [1.0, 2.0, 3.0, 4.0],
    }
    assert events_of(events, "evaluation_scored")[0]["scenario"] == "C1"
    raw = trace.path.read_text(encoding="utf-8")
    assert "must-not-appear" not in raw
    assert "D:\\private" not in raw
    assert "evaluation_scored" in format_trace(events, request_id)


def test_model_exception_is_flushed_without_exposing_error_text(tmp_path):
    trace = Trace(tmp_path)
    with pytest.raises(RuntimeError, match="private details"):
        with trace.request(1, session_id="session"):
            with trace.model_call("fake"):
                raise RuntimeError("private details")
    trace.scored({"success": False, "rule_breaks": [],
                  "failed_checks": ["run crashed: RuntimeError: private details"]}, "C1")

    events = read_trace(trace.path)
    assert validate_trace(trace.path) == []
    assert events_of(events, "model_failed")[0]["error_type"] == "RuntimeError"
    assert events_of(events, "chat_failed")[0]["error_type"] == "RuntimeError"
    assert events_of(events, "evaluation_scored")[0]["failed_checks"] == [
        "run crashed; see the failure events for the exception type",
    ]
    assert "private details" not in trace.path.read_text(encoding="utf-8")


def test_tool_exception_keeps_machine_and_failure_events(tmp_path):
    trace = Trace(tmp_path)
    with pytest.raises(OSError):
        with trace.request(1, session_id="session"):
            with trace.model_call("fake"):
                pass
            with trace.tool_call("auto_scan", {"slide": 1}):
                trace.machine_events([("socket", "StartScan", {"slide_no": 0})])
                raise OSError("connection lost")

    events = read_trace(trace.path)
    assert validate_trace(trace.path) == []
    assert events_of(events, "machine_action")[0]["action"] == "StartScan"
    assert events_of(events, "tool_failed")[0]["error_type"] == "OSError"
    assert events_of(events, "chat_failed")[0]["error_type"] == "OSError"


def test_requested_but_undispatched_tool_is_explicitly_blocked(tmp_path):
    trace = Trace(tmp_path)
    with trace.request(1, session_id="session") as request:
        with trace.model_call("fake"):
            pass
        trace.tool_requested("auto_scan", "provider-call", {"slide": None})
        request.complete(reply_returned=True)

    events = read_trace(trace.path)
    assert validate_trace(trace.path) == []
    blocked = events_of(events, "tool_not_dispatched")
    assert len(blocked) == 1
    assert blocked[0]["status"] == "blocked"
    assert blocked[0]["tool"] == "auto_scan"


def test_interleaved_requests_do_not_cross_context(tmp_path):
    trace = Trace(tmp_path)
    barrier = threading.Barrier(2)
    errors = []

    def worker(turn):
        try:
            with trace.request(turn, session_id=f"session-{turn}"):
                barrier.wait()
                with trace.model_call("fake"):
                    barrier.wait()
        except Exception as error:
            errors.append(error)

    threads = [threading.Thread(target=worker, args=(turn,)) for turn in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []

    events = read_trace(trace.path)
    assert validate_trace(trace.path) == []
    assert len({event["request_id"] for event in events_of(events, "chat_started")}) == 2
    assert len(events_of(events, "model_completed")) == 2


def test_validator_rejects_orphan_machine_action(tmp_path):
    trace = Trace(tmp_path)
    trace.run_completed()
    events = read_trace(trace.path)
    events.append({"schema_version": 1, "trace_id": trace.trace_id,
                   "sequence": len(events) + 1, "timestamp": "now", "event": "machine_action",
                   "request_id": "unknown", "tool_call_id": "unknown"})
    assert any("uncorrelated machine action" in problem for problem in validate_events(events))
