"""M4 driver: one customer conversation with the REAL co-pilot and the REAL language
model, on the virtual scanner.

It drives the co-pilot exactly like the browser does - start a session, then send
the customer's messages one by one - and measures everything from the OUTSIDE:

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
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from virtual_scanner import VirtualScanner  # noqa: E402
from virtual_scanner.harness import _inside, load_copilot  # noqa: E402

# The machine's broken system proxy would block the model API (not the scanner).
for _var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(_var, None)


class Meter:
    """Wraps the co-pilot's model client and tool runner; records every call."""

    def __init__(self, main):
        self.model_calls = []
        self.tool_calls = []
        self.turn = 0                     # 0 = the greeting, n = the customer's n-th message
        create = main.client.chat.completions.create
        run_tool = main._run_tool_by_name

        def metered_create(*args, **kwargs):
            t0 = time.time()
            response = create(*args, **kwargs)
            usage = getattr(response, "usage", None)
            u = usage.model_dump() if hasattr(usage, "model_dump") else dict(usage or {})
            self.model_calls.append({
                "turn": self.turn,
                "model": kwargs.get("model"),
                "seconds": round(time.time() - t0, 2),
                "prompt_tokens": u.get("prompt_tokens", 0),
                "completion_tokens": u.get("completion_tokens", 0),
                "cached_tokens": u.get("prompt_cache_hit_tokens",
                                       (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0)) or 0,
                "asked_for_tools": [tc.function.name for tc in
                                    (response.choices[0].message.tool_calls or [])],
            })
            return response

        def metered_tool(*args, **kwargs):
            name = args[0] if args else kwargs.get("tool_name")
            tool_args = args[1] if len(args) > 1 else kwargs.get("args")
            t0 = time.time()
            result = run_tool(*args, **kwargs)
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

        main.client.chat.completions.create = metered_create
        main._run_tool_by_name = metered_tool


def run_conversation(private_root, script, mode="brightfield", loaded=("clear", None, None, None),
                     faults=(), fake_model=None, setup=()):
    """Start a Customer session and send `script` (the customer's messages) one by one.

    `loaded`: what is in each loader position (None = empty). `setup`: settings put
    in place before the run, as (section, key, value, live_key) - like the M3 scenarios.
    `fake_model`: a stand-in for the model API (offline plumbing tests, no tokens).
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
    meter = Meter(main)
    config_sha_before = hashlib.sha256(twin.config_path.read_bytes()).hexdigest()

    transcript, t0, error = [], time.time(), None
    try:
        # The co-pilot reads its knowledge files relative to its own folder.
        with _inside(str(Path(private_root).resolve())):
            started = main.start(main.StartRequest(mode=mode, audience="customer"))
            session_id = started["session_id"]
            transcript.append({"role": "copilot", "text": started["reply"]})
            for meter.turn, message in enumerate(script, start=1):
                transcript.append({"role": "customer", "text": message})
                reply = main.chat(main.ChatMessage(session_id=session_id, message=message))
                transcript.append({"role": "copilot", "text": reply.get("reply", "")})
    except Exception as e:                        # a crash is a result too
        error = f"{type(e).__name__}: {e}"

    return {"mode": mode, "faults": list(faults), "script": list(script),
            "transcript": transcript, "model_calls": meter.model_calls,
            "tool_calls": meter.tool_calls, "twin": twin,
            "config_sha_before": config_sha_before,
            "knowledge_dir": str(work / "knowledge"),     # where a confirmed reference would be saved
            # the support codes the co-pilot really has - anything else told to a customer is invented
            "known_codes": sorted(set(main.CUSTOMER_FAILURES) | {"SPEED-FIX"}),
            "seconds": round(time.time() - t0, 1), "error": error}


def summary(run):
    """The parts of a run that are safe to print or save (no scanner object)."""
    calls = run["model_calls"]
    return {k: v for k, v in run.items() if k != "twin"} | {
        "totals": {"model_calls": len(calls),
                   "prompt_tokens": sum(c["prompt_tokens"] for c in calls),
                   "cached_tokens": sum(c["cached_tokens"] for c in calls),
                   "completion_tokens": sum(c["completion_tokens"] for c in calls)}}


if __name__ == "__main__":
    # One conversation, printed - for a first look by hand.
    private = sys.argv[1] if len(sys.argv) > 1 else str(REPO.parent)
    run = run_conversation(private, ["start scan", "1"])
    print(json.dumps(summary(run), indent=2, ensure_ascii=False, default=str))
