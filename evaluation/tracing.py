"""M7: correlated, JSON-safe traces for co-pilot evaluation runs."""
import json
import re
import threading
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
_CURRENT_REQUEST = ContextVar("m7_request", default=None)
_CURRENT_MODEL = ContextVar("m7_model", default=None)
_CURRENT_TOOL = ContextVar("m7_tool", default=None)

_FIELDS = {
    "status", "request_kind", "mode", "audience", "model", "duration_ms",
    "prompt_tokens", "completion_tokens", "cached_tokens", "asked_for_tools",
    "tool", "provider_call_id", "model_call_id", "tool_call_id", "arguments",
    "ok", "support_code", "quality", "level", "still_scanning", "door", "action",
    "detail", "error_type", "reply_returned", "scenario", "repeat", "success",
    "unsafe", "false_success", "false_failure", "attack_success", "invented_code",
    "correct_escalation", "failed_checks", "rule_breaks",
}
_ARGUMENT_KEYS = {
    "slide", "slide_no", "mode", "value", "left_mm", "top_mm", "width_mm",
    "height_mm", "x", "y", "z", "count", "scan_anyway", "looks_right", "box",
}
_REASON_KEYS = {"failed_checks", "rule_breaks"}
_BOOL_FIELDS = {
    "ok", "still_scanning", "reply_returned", "success", "unsafe", "false_success",
    "false_failure", "attack_success", "invented_code", "correct_escalation",
}
_WINDOWS_PATH = re.compile(r"\b[A-Za-z]:[\\/][^\s\"']+")


def _redact(text):
    text = str(text)
    if text.startswith("run crashed:"):
        return "run crashed; see the failure events for the exception type"
    return _WINDOWS_PATH.sub("[path]", text)


def _safe_scalar(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = str(value)
    return text[:64] if re.fullmatch(r"[A-Za-z0-9_.-]+", text) else "[text]"


def _safe_arguments(arguments):
    if not isinstance(arguments, dict):
        return {}
    safe = {}
    for key, value in arguments.items():
        if key not in _ARGUMENT_KEYS:
            continue
        if key == "box" and isinstance(value, (list, tuple)):
            safe[key] = [v for v in value if isinstance(v, (int, float)) and not isinstance(v, bool)]
        else:
            safe[key] = _safe_scalar(value)
    return safe


def _safe_detail(detail):
    if isinstance(detail, dict):
        return _safe_arguments(detail)
    if isinstance(detail, (int, float)) and not isinstance(detail, bool):
        return detail
    return None


@dataclass
class Span:
    fields: dict = field(default_factory=dict)

    def complete(self, **fields):
        self.fields.update(fields)


@dataclass
class RequestContext:
    trace: object
    request_id: str
    session_id: str | None
    turn: int
    last_model_call_id: str | None = None
    requested_tools: list = field(default_factory=list)
    dispatched_tools: list = field(default_factory=list)
    response_fields: dict = field(default_factory=dict)

    def bind_session(self, session_id):
        self.session_id = session_id
        self.trace.event("session_started")

    def complete(self, reply_returned):
        self.response_fields["reply_returned"] = bool(reply_returned)


class Trace:
    def __init__(self, directory, trace_id=None):
        self.trace_id = trace_id or uuid.uuid4().hex
        self.path = Path(directory) / f"{self.trace_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._sequence = 0
        self._lock = threading.Lock()
        self.event("run_started")

    def event(self, event, **fields):
        request = _CURRENT_REQUEST.get()
        model = _CURRENT_MODEL.get()
        tool = _CURRENT_TOOL.get()
        with self._lock:
            self._sequence += 1
            data = {
                "schema_version": SCHEMA_VERSION,
                "trace_id": self.trace_id,
                "sequence": self._sequence,
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "event": event,
            }
            if request is not None and request.trace is self:
                data.update(request_id=request.request_id, session_id=request.session_id,
                            turn=request.turn)
            if model is not None:
                data["model_call_id"] = model
            if tool is not None:
                data.update(tool_call_id=tool["id"], model_call_id=tool["model_call_id"])
            for key, value in fields.items():
                if key not in _FIELDS or value is None:
                    continue
                if key == "arguments":
                    value = _safe_arguments(value)
                elif key == "detail":
                    value = _safe_detail(value)
                    if value is None:
                        continue
                elif key in _REASON_KEYS:
                    value = [_redact(v) for v in value]
                elif key == "asked_for_tools":
                    value = [str(v) for v in value]
                elif key in _BOOL_FIELDS:
                    value = bool(value)
                data[key] = value
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")
                stream.flush()

    @contextmanager
    def request(self, turn, session_id=None, request_kind="chat", mode=None, audience=None):
        request = RequestContext(self, uuid.uuid4().hex, session_id, turn)
        token = _CURRENT_REQUEST.set(request)
        self.event("chat_started", request_kind=request_kind, mode=mode, audience=audience)
        try:
            yield request
        except Exception as error:
            self._not_dispatched(request)
            self.event("chat_failed", status="error", error_type=type(error).__name__)
            raise
        else:
            self._not_dispatched(request)
            self.event("chat_completed", status="ok", **request.response_fields)
        finally:
            _CURRENT_REQUEST.reset(token)

    def _not_dispatched(self, request):
        remaining = list(request.requested_tools)
        for name in request.dispatched_tools:
            match = next((i for i, item in enumerate(remaining) if item["tool"] == name), None)
            if match is not None:
                remaining.pop(match)
        for item in remaining:
            self.event("tool_not_dispatched", status="blocked", **item)

    def bind_session(self, session_id):
        request = _CURRENT_REQUEST.get()
        if request is not None and request.trace is self:
            request.bind_session(session_id)

    @contextmanager
    def model_call(self, model):
        request = _CURRENT_REQUEST.get()
        call_id = uuid.uuid4().hex
        if request is not None:
            request.last_model_call_id = call_id
        token = _CURRENT_MODEL.set(call_id)
        started = time.perf_counter()
        span = Span()
        self.event("model_started", model=model, model_call_id=call_id)
        try:
            yield span
        except Exception as error:
            self.event("model_failed", status="error", error_type=type(error).__name__,
                       duration_ms=round((time.perf_counter() - started) * 1000, 2))
            raise
        else:
            self.event("model_completed", status="ok",
                       duration_ms=round((time.perf_counter() - started) * 1000, 2), **span.fields)
        finally:
            _CURRENT_MODEL.reset(token)

    def tool_requested(self, tool, provider_call_id, arguments, model_call_id=None):
        request = _CURRENT_REQUEST.get()
        if model_call_id is None and request is not None:
            model_call_id = request.last_model_call_id
        item = {"tool": tool, "provider_call_id": provider_call_id,
                "arguments": arguments, "model_call_id": model_call_id}
        if request is not None:
            request.requested_tools.append(item)
        self.event("tool_requested", status="requested", **item)

    @contextmanager
    def tool_call(self, tool, arguments):
        request = _CURRENT_REQUEST.get()
        model_call_id = request.last_model_call_id if request is not None else None
        if request is not None:
            request.dispatched_tools.append(tool)
        call_id = uuid.uuid4().hex
        token = _CURRENT_TOOL.set({"id": call_id, "model_call_id": model_call_id})
        started = time.perf_counter()
        span = Span()
        self.event("tool_started", tool=tool, arguments=arguments)
        try:
            yield span
        except Exception as error:
            self.event("tool_failed", status="error", error_type=type(error).__name__,
                       duration_ms=round((time.perf_counter() - started) * 1000, 2))
            raise
        else:
            self.event("tool_completed", status="ok",
                       duration_ms=round((time.perf_counter() - started) * 1000, 2), **span.fields)
        finally:
            _CURRENT_TOOL.reset(token)

    def machine_events(self, entries):
        for door, action, detail in entries:
            self.event("machine_action", door=door, action=action, detail=detail)

    def scored(self, score, scenario, repeat=None):
        keys = ("success", "unsafe", "false_success", "false_failure", "attack_success",
                "invented_code", "correct_escalation", "failed_checks", "rule_breaks")
        self.event("evaluation_scored", scenario=scenario, repeat=repeat,
                   **{key: score.get(key) for key in keys if key in score})

    def run_completed(self, error=None):
        self.event("run_completed", status="error" if error else "ok",
                   error_type=type(error).__name__ if error else None)


def record_score(run, score, scenario, repeat=None):
    trace = run.get("trace")
    if trace is not None:
        trace.scored(score, scenario, repeat)


def read_trace(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]


def validate_events(events):
    problems = []
    if not events:
        return ["trace has no events"]
    trace_ids = {event.get("trace_id") for event in events}
    if len(trace_ids) != 1:
        problems.append("trace contains multiple or missing trace IDs")
    sequences = [event.get("sequence") for event in events]
    if sequences != list(range(1, len(events) + 1)):
        problems.append("event sequence is not contiguous and ordered")

    chats, models, tools = {}, {}, {}
    for event in events:
        kind = event.get("event")
        request_id = event.get("request_id")
        sequence = event.get("sequence")
        if kind == "chat_started":
            if not request_id or request_id in chats:
                problems.append(f"sequence {sequence}: invalid or duplicate chat start")
            chats[request_id] = 0
        elif kind in ("chat_completed", "chat_failed"):
            if request_id not in chats:
                problems.append(f"sequence {sequence}: orphan {kind}")
            else:
                chats[request_id] += 1
        elif kind == "model_started":
            call_id = event.get("model_call_id")
            if not request_id or not call_id or call_id in models:
                problems.append(f"sequence {sequence}: invalid model start")
            models[call_id] = [request_id, 0]
        elif kind in ("model_completed", "model_failed"):
            call_id = event.get("model_call_id")
            if call_id not in models or models[call_id][0] != request_id:
                problems.append(f"sequence {sequence}: orphan or crossed {kind}")
            else:
                models[call_id][1] += 1
        elif kind in ("tool_requested", "tool_not_dispatched"):
            call_id = event.get("model_call_id")
            if call_id not in models or models[call_id][0] != request_id:
                problems.append(f"sequence {sequence}: orphan or crossed {kind}")
        elif kind == "tool_started":
            call_id = event.get("tool_call_id")
            model_id = event.get("model_call_id")
            if not request_id or not call_id or call_id in tools:
                problems.append(f"sequence {sequence}: invalid tool start")
            if model_id not in models or models[model_id][0] != request_id:
                problems.append(f"sequence {sequence}: tool start has an orphan or crossed model call")
            tools[call_id] = [request_id, 0]
        elif kind in ("tool_completed", "tool_failed"):
            call_id = event.get("tool_call_id")
            if call_id not in tools or tools[call_id][0] != request_id:
                problems.append(f"sequence {sequence}: orphan or crossed {kind}")
            else:
                tools[call_id][1] += 1
        elif kind == "machine_action":
            call_id = event.get("tool_call_id")
            if call_id not in tools or tools[call_id][0] != request_id:
                problems.append(f"sequence {sequence}: uncorrelated machine action")

    problems += [f"request {request_id} has {count} terminal events"
                 for request_id, count in chats.items() if count != 1]
    problems += [f"model call {call_id} has {state[1]} terminal events"
                 for call_id, state in models.items() if state[1] != 1]
    problems += [f"tool call {call_id} has {state[1]} terminal events"
                 for call_id, state in tools.items() if state[1] != 1]
    return problems


def validate_trace(path):
    return validate_events(read_trace(path))


def format_trace(events, request_id=None):
    if not events:
        return "Empty trace."
    selected = [event for event in events
                if request_id is None or event.get("request_id") in (None, request_id)]
    lines = [f"TRACE {events[0].get('trace_id')} — {len(selected)} event(s)"]
    base = {"schema_version", "trace_id", "sequence", "timestamp", "event", "session_id"}
    for event in selected:
        details = {key: value for key, value in event.items() if key not in base}
        lines.append(f"{event['sequence']:>4} {event['timestamp']} {event['event']:<24} "
                     + json.dumps(details, ensure_ascii=False, default=str))
    return "\n".join(lines)
