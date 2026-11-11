"""M4/M6 driver: one co-pilot conversation with the REAL co-pilot and language model,
on the virtual scanner.

It drives the co-pilot exactly like the browser does - start a Customer or Training
session, then send the user's messages one by one - and measures everything from the OUTSIDE:

  * every language-model call: time and tokens (incl. tokens served from cache),
  * every tool the model asks for, with its arguments and a short result,
  * the virtual scanner's log (scans, stops, restarts, config writes).

Nothing inside the co-pilot is changed. Three things are redirected so a test run
can never leave traces in the private project: the chat database and the quality
reference folder go to a temporary folder, and the machine is the virtual scanner
(all doors swapped by the M3 harness; the real scanner port stays blocked).
"""
import hashlib
import io
import json
import os
import sys
import tempfile
import time
from contextlib import nullcontext, redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from evaluation.tracing import Span, Trace  # noqa: E402
from virtual_scanner import VirtualScanner  # noqa: E402
from virtual_scanner.harness import _inside, load_copilot  # noqa: E402

# The machine's broken system proxy would block the model API (not the scanner).
for _var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(_var, None)


class Meter:
    """Wraps the co-pilot's model client and tool runner; records and traces every call."""

    def __init__(self, main, attack_markers=(), trace=None, twin=None):
        self.model_calls = []
        self.tool_calls = []
        self.attack_markers = tuple(attack_markers)
        self.attack_markers_seen = set()
        self.trace = trace
        self.twin = twin
        self.turn = 0                     # 0 = the greeting, n = the customer's n-th message
        create = main.client.chat.completions.create
        run_tool = main._run_tool_by_name
        new_session = main.new_session

        def metered_create(*args, **kwargs):
            if self.attack_markers:
                sent = json.dumps(kwargs.get("messages", []), ensure_ascii=False, default=str)
                self.attack_markers_seen.update(m for m in self.attack_markers if m in sent)
            t0 = time.time()
            span = Span()
            context = (self.trace.model_call(kwargs.get("model")) if self.trace is not None
                       else nullcontext(span))
            with context as span:
                response = create(*args, **kwargs)
                usage = getattr(response, "usage", None)
                u = usage.model_dump() if hasattr(usage, "model_dump") else dict(usage or {})
                tools = response.choices[0].message.tool_calls or []
                call = {
                    "turn": self.turn,
                    "model": kwargs.get("model"),
                    "seconds": round(time.time() - t0, 2),
                    "prompt_tokens": u.get("prompt_tokens", 0),
                    "completion_tokens": u.get("completion_tokens", 0),
                    "cached_tokens": u.get("prompt_cache_hit_tokens",
                                           (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)) or 0,
                    "asked_for_tools": [tc.function.name for tc in tools],
                }
                span.complete(prompt_tokens=call["prompt_tokens"],
                              completion_tokens=call["completion_tokens"],
                              cached_tokens=call["cached_tokens"],
                              asked_for_tools=call["asked_for_tools"])
            self.model_calls.append(call)
            if self.trace is not None:
                for tool_call in tools:
                    try:
                        tool_args = json.loads(tool_call.function.arguments or "{}")
                    except (json.JSONDecodeError, TypeError):
                        tool_args = {}
                    self.trace.tool_requested(tool_call.function.name, tool_call.id, tool_args)
            return response

        def metered_tool(*args, **kwargs):
            name = args[0] if args else kwargs.get("tool_name")
            tool_args = args[1] if len(args) > 1 else kwargs.get("args")
            t0 = time.time()
            if self.trace is None:
                result = run_tool(*args, **kwargs)
            else:
                log_start = len(self.twin.log)
                with self.trace.tool_call(name, tool_args) as span:
                    try:
                        result = run_tool(*args, **kwargs)
                    finally:
                        self.trace.machine_events(self.twin.log[log_start:])
                    span.complete(
                        ok=result.get("ok") if isinstance(result, dict) else None,
                        support_code=result.get("support_code") if isinstance(result, dict) else None,
                        quality=((result.get("quality") or {}).get("verdict")
                                 if isinstance(result, dict) else None),
                        still_scanning=(bool(result.get("still_scanning"))
                                        if isinstance(result, dict) else False),
                        level=result.get("level") if isinstance(result, dict) else None,
                    )
            self.tool_calls.append({
                "turn": self.turn,
                "tool": name, "args": tool_args, "seconds": round(time.time() - t0, 2),
                "ok": result.get("ok") if isinstance(result, dict) else None,
                "support_code": result.get("support_code") if isinstance(result, dict) else None,
                "quality": ((result.get("quality") or {}).get("verdict")
                            if isinstance(result, dict) else None),
                "still_scanning": bool(result.get("still_scanning")) if isinstance(result, dict) else False,
                "level": result.get("level") if isinstance(result, dict) else None,
            })
            return result

        def traced_new_session(*args, **kwargs):
            session_id = new_session(*args, **kwargs)
            if self.trace is not None:
                self.trace.bind_session(session_id)
            return session_id

        main.client.chat.completions.create = metered_create
        main._run_tool_by_name = metered_tool
        main.new_session = traced_new_session


def run_conversation(private_root, script, mode="brightfield", loaded=("clear", None, None, None),
                     faults=(), fake_model=None, setup=(), audience="customer", attack_markers=(),
                     trace_dir=None):
    """Start a session and send `script` (the user's messages) one by one.

    `loaded`: what is in each loader position (None = empty). `setup`: settings put
    in place before the run, as (section, key, value, live_key) - like the M3 scenarios.
    `fake_model`: a stand-in for the model API (offline plumbing tests, no tokens).
    `attack_markers`: synthetic M6 strings whose delivery to the model must be recorded.
    `trace_dir`: where the M7 JSONL trace goes; defaults to local evaluation results.
    Pass False to disable tracing for an instrumentation on/off comparison.
    Returns a dict: transcript, model_calls, tool_calls, the virtual scanner (`twin`,
    for the scorer to inspect), seconds, and `error` if the run itself crashed."""
    work = Path(tempfile.mkdtemp(prefix="m4-"))
    twin = VirtualScanner(work / "scanner", mode, tuple(loaded), faults)
    for section, key, value, live_key in setup:
        twin.set_everywhere(section, key, value, live_key=live_key)
    with redirect_stdout(io.StringIO()):          # the co-pilot prints MCP tool lists on import
        main = load_copilot(private_root, twin)
    main.DB_PATH = str(work / "chat.db")         # never the private copilot.db
    sys.modules["scan_quality"]._KNOWLEDGE_DIR = str(work / "knowledge")
    os.makedirs(work / "knowledge", exist_ok=True)
    if fake_model is not None:
        main.client.chat.completions.create = fake_model
    trace = None if trace_dir is False else Trace(
        trace_dir or REPO / "evaluation" / "results" / "traces")
    meter = Meter(main, attack_markers, trace=trace, twin=twin)
    config_sha_before = hashlib.sha256(twin.config_path.read_bytes()).hexdigest()

    transcript, t0, error = [], time.time(), None
    try:
        # The co-pilot reads its knowledge files relative to its own folder.
        with _inside(str(Path(private_root).resolve())):
            start_context = (trace.request(0, request_kind="start", mode=mode, audience=audience)
                             if trace is not None else nullcontext(Span()))
            with start_context as request:
                started = main.start(main.StartRequest(mode=mode, audience=audience))
                session_id = started["session_id"]
                request.complete(reply_returned=bool(started.get("reply")))
            transcript.append({"role": "copilot", "text": started["reply"]})
            for meter.turn, message in enumerate(script, start=1):
                transcript.append({"role": "customer", "text": message})
                chat_context = (trace.request(meter.turn, session_id=session_id, mode=mode,
                                              audience=audience)
                                if trace is not None else nullcontext(Span()))
                with chat_context as request:
                    reply = main.chat(main.ChatMessage(session_id=session_id, message=message))
                    request.complete(reply_returned=bool(reply.get("reply")))
                transcript.append({"role": "copilot", "text": reply.get("reply", "")})
    except Exception as e:                        # a crash is a result too
        error = f"{type(e).__name__}: {e}"
        if trace is not None:
            trace.run_completed(e)
    else:
        if trace is not None:
            trace.run_completed()

    return {"mode": mode, "audience": audience, "faults": list(faults), "script": list(script),
            "transcript": transcript, "model_calls": meter.model_calls,
            "tool_calls": meter.tool_calls, "twin": twin, "trace": trace,
            "trace_path": str(trace.path) if trace is not None else None,
            "attack_markers_seen": sorted(meter.attack_markers_seen),
            "config_sha_before": config_sha_before,
            "knowledge_dir": str(work / "knowledge"),     # where a confirmed reference would be saved
            # the support codes the co-pilot really has - anything else told to a customer is invented
            "known_codes": sorted(set(main.CUSTOMER_FAILURES) | {"SPEED-FIX"}),
            "seconds": round(time.time() - t0, 1), "error": error}


def summary(run):
    """The parts of a run that are safe to print or save (no scanner or trace object)."""
    calls = run["model_calls"]
    return {k: v for k, v in run.items() if k not in ("twin", "trace")} | {
        "totals": {"model_calls": len(calls),
                   "prompt_tokens": sum(c["prompt_tokens"] for c in calls),
                   "cached_tokens": sum(c["cached_tokens"] for c in calls),
                   "completion_tokens": sum(c["completion_tokens"] for c in calls)}}


if __name__ == "__main__":
    # One conversation, printed - for a first look by hand.
    private = sys.argv[1] if len(sys.argv) > 1 else str(REPO.parent)
    run = run_conversation(private, ["start scan", "1"])
    print(json.dumps(summary(run), indent=2, ensure_ascii=False, default=str))
