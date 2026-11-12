"""HDScanner AI Co-Pilot — reference skeleton (generic agent engineering).

This is the reusable, provider-agnostic core of an LLM agent with tool-calling,
distilled from a production support-agent build. It demonstrates:

  1. A multi-turn tool-calling loop (DeepSeek / any OpenAI-compatible API).
  2. Per-session conversation isolation + SQLite persistence (history survives
     restarts, and concurrent users each get their own conversation).
  3. Crash-safe conversation handling — a failed turn rolls back instead of
     corrupting the shared history, and dangling tool calls self-heal.
  4. Recovery of "leaked" tool calls (some models emit tool calls as plain-text
     markup instead of the structured field — this parses and re-runs them).

Everything hardware-specific (the scanner protocol, the vendor knowledge base,
screenshots) has been intentionally removed from this public copy. The generic
tool loop below uses a trivial example tool so the pattern is runnable out of
the box. To adapt this to your own domain, replace the TOOLS list and the
run_tool() dispatcher with your own integrations.
"""

import os
import re
import json
import uuid
import sqlite3
from datetime import datetime

from dotenv import load_dotenv
from openai import OpenAI
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.versioning import load_runtime_version

load_dotenv()

# ---------------------------------------------------------------------------
# LLM client — any OpenAI-compatible API works here. DeepSeek is used in the
# original build (base_url="https://api.deepseek.com", model "deepseek-chat").
# ---------------------------------------------------------------------------
client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
)

CHAT_MODEL = os.getenv("CHAT_MODEL", "deepseek-chat")
VERSION_INFO = load_runtime_version()

# ---------------------------------------------------------------------------
# Example tools — replace these with your own domain actions. They exist so the
# tool-calling loop below is demonstrable; in the real build these were the
# scanner's own commands (preview, scan, read state), plus a curated allowlist.
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "current_time",
            "description": "Get the server's current date and time.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_numbers",
            "description": "Add two numbers together and return the sum.",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "First number"},
                    "b": {"type": "number", "description": "Second number"},
                },
                "required": ["a", "b"],
            },
        },
    },
]


def run_tool(name: str, arguments: dict) -> dict:
    """Execute one tool. OUR code runs the action — the model only asked.

    Always return a safe dict; never raise. In the real build this dispatcher
    was where every integration lived, each wrapped so a failure could never
    crash the chat loop.
    """
    try:
        if name == "current_time":
            return {"ok": True, "now": datetime.now().isoformat()}
        if name == "add_numbers":
            return {"ok": True, "sum": float(arguments["a"]) + float(arguments["b"])}
        return {"error": f"Unknown tool: {name}"}
    except Exception as e:  # noqa: BLE001 — a tool error must not break the loop
        return {"error": f"Tool {name} failed: {e}"}


# ---------------------------------------------------------------------------
# Leaked-tool-call recovery.
#
# The API is *supposed* to return tool calls in the structured `tool_calls`
# field. But some models intermittently emit the call as TEXT in
# message.content using internal markup (e.g. `<...invoke name="X"> ...`).
# When that happens the action silently doesn't run and the raw markup would
# show to the user. These helpers detect that markup, recover the intended
# call, and let the tool loop execute it for real — a leak becomes a real
# action, never visible junk.
# ---------------------------------------------------------------------------
_INVOKE_RE = re.compile(r'invoke\s+name="([^"]+)"(.*?)(?:</[^>]*invoke|$)', re.DOTALL)
_PARAM_RE = re.compile(r'parameter\s+name="([^"]+)"[^>]*?>(.*?)</[^>]*parameter', re.DOTALL)


def _looks_like_tool_markup(content: str) -> bool:
    return bool(content) and ("invoke name=" in content or "DSML" in content)


def parse_leaked_tool_calls(content: str) -> list:
    """Recover [(tool_name, args_dict), ...] from leaked tool-call markup in text.

    Returns [] if none is found.
    """
    if not _looks_like_tool_markup(content):
        return []
    calls = []
    for m in _INVOKE_RE.finditer(content):
        name = m.group(1).strip()
        args = {}
        for pm in _PARAM_RE.finditer(m.group(2)):
            key = pm.group(1).strip()
            val_text = pm.group(2).strip()
            try:
                val = json.loads(val_text)  # numbers / bools / json values
            except (json.JSONDecodeError, ValueError):
                val = val_text              # plain string
            args[key] = val
        calls.append((name, args))
    return calls


def strip_tool_markup(content: str) -> str:
    """Last-resort cleanup: remove any unrecoverable tool-call markup so the
    user never sees raw tokens."""
    if not _looks_like_tool_markup(content):
        return content
    cleaned = re.sub(r"<[^>]*>", "", content)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned or "Okay — done."


# ---------------------------------------------------------------------------
# Knowledge / system prompt.
#
# The real build loaded a large domain knowledge base into the system prompt.
# Here it's a single placeholder so the app runs standalone. To adapt: replace
# this with your own instructions, or move to retrieval (RAG) once the content
# grows large enough that "stuff everything in the prompt" stops scaling.
# ---------------------------------------------------------------------------
def load_knowledge() -> str:
    try:
        with open("knowledge/system_prompt.md", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "You are a helpful assistant. Answer clearly and concisely."


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI()
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
def root():
    return FileResponse("app/static/index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/version")
def version():
    return VERSION_INFO


# ---------------------------------------------------------------------------
# Conversation storage — per-session isolation + SQLite persistence.
#
# Each conversation is identified by a session id the browser keeps (in
# localStorage). History is written to a SQLite file on disk on every turn, so
# it survives server restarts, --reload, and crashes. The interface
# (new_session / get_session) is what the endpoints use; only the storage
# backend changed when this moved from an in-memory dict to SQLite.
# ---------------------------------------------------------------------------
DB_PATH = os.getenv("DB_PATH", "copilot.db")


def _db() -> sqlite3.Connection:
    """Open the DB and make sure the table exists. Returns an open connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id   TEXT PRIMARY KEY,
            uses_vision  INTEGER NOT NULL DEFAULT 0,
            conversation TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _save_session(session_id: str, uses_vision: bool, conversation: list):
    conn = _db()
    conn.execute(
        "INSERT OR REPLACE INTO sessions (session_id, uses_vision, conversation) "
        "VALUES (?, ?, ?)",
        (session_id, 1 if uses_vision else 0,
         json.dumps(conversation, ensure_ascii=False, default=str)),
    )
    conn.commit()
    conn.close()


def new_session() -> str:
    """Create a fresh session persisted to disk. Returns its id."""
    session_id = uuid.uuid4().hex
    _save_session(session_id, False, [{"role": "system", "content": load_knowledge()}])
    return session_id


def get_session(session_id: str) -> dict | None:
    """Load a session's conversation from disk, or None if unknown."""
    conn = _db()
    row = conn.execute(
        "SELECT uses_vision, conversation FROM sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return {"uses_vision": bool(row[0]), "conversation": json.loads(row[1])}


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class ChatMessage(BaseModel):
    session_id: str
    message: str
    image_base64: str | None = None


@app.post("/api/start")
def start():
    session_id = new_session()
    sess = get_session(session_id)
    conversation = sess["conversation"]

    response = client.chat.completions.create(model=CHAT_MODEL, messages=conversation)
    reply = response.choices[0].message.content
    conversation.append({"role": "assistant", "content": reply})
    _save_session(session_id, sess["uses_vision"], conversation)

    return {"session_id": session_id, "reply": reply}


@app.get("/api/session/{session_id}")
def get_conversation(session_id: str):
    """Return a session's human-facing messages so the browser can re-draw the
    conversation after a refresh. Skips the internal system prompt and tool-call
    plumbing — only user text and assistant replies are shown."""
    sess = get_session(session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="Session not found.")

    messages = []
    for m in sess["conversation"]:
        role = m.get("role")
        if role == "user":
            content = m.get("content")
            if isinstance(content, list):
                text = "".join(p.get("text", "") for p in content if p.get("type") == "text")
            else:
                text = content or ""
            messages.append({"role": "user", "content": text})
        elif role == "assistant":
            content = m.get("content")
            if isinstance(content, str) and content.strip():
                messages.append({"role": "assistant", "content": content})

    return {"messages": messages}


def _heal_dangling_tool_calls(conversation):
    """Repair the conversation if a previous turn crashed mid-tool-loop and left
    an assistant `tool_calls` message without its matching `tool` responses.
    The API rejects that on the next call ('tool_calls must be followed by tool
    messages'), which would 500 every request until restart. We drop such a
    dangling trailing assistant message so the chat recovers itself."""
    while conversation:
        last = conversation[-1]
        role = last.get("role") if isinstance(last, dict) else None
        if role == "assistant" and last.get("tool_calls"):
            conversation.pop()
            continue
        break


@app.post("/api/chat")
def chat(chat_message: ChatMessage):
    sess = get_session(chat_message.session_id)
    if sess is None:
        return {"reply": "I don't recognise this conversation (it may have been "
                         "restarted). Please refresh the page to begin."}

    conversation = sess["conversation"]
    session_id = chat_message.session_id

    # Recover from any prior half-finished tool turn before we call the API.
    _heal_dangling_tool_calls(conversation)
    # Snapshot BEFORE touching the conversation, so a failed turn can roll back.
    snapshot = list(conversation)

    if chat_message.image_base64:
        sess["uses_vision"] = True
        user_content = [
            {"type": "text", "text": chat_message.message},
            {"type": "image_url",
             "image_url": {"url": chat_message.image_base64, "detail": "high"}},
        ]
    else:
        user_content = chat_message.message

    conversation.append({"role": "user", "content": user_content})

    # The tool loop. The model may ask to call a tool; WE run it, feed the result
    # back, and let the model reply. Repeat until a normal text answer (capped).
    # Wrapped so ANY failure rolls the shared history back to `snapshot`.
    try:
        message = None
        for _ in range(5):  # safety cap so we can never loop forever
            response = client.chat.completions.create(
                model=CHAT_MODEL,
                messages=conversation,
                tools=TOOLS,
            )
            message = response.choices[0].message

            # Recover tool calls leaked as text (some models do this).
            recovered = None
            if not message.tool_calls:
                recovered = parse_leaked_tool_calls(message.content or "")

            # A genuine text answer (no calls, no leaked markup): we're done.
            if not message.tool_calls and not recovered:
                conversation.append(message.model_dump(exclude_none=True))
                _save_session(session_id, sess["uses_vision"], conversation)
                return {"reply": strip_tool_markup(message.content)}

            # Build a uniform list of (id, name, raw_args) to run, and append a
            # proper assistant message so the following role:"tool" replies stay valid.
            if message.tool_calls:
                conversation.append(message.model_dump(exclude_none=True))
                calls = [(tc.id, tc.function.name, tc.function.arguments)
                         for tc in message.tool_calls]
            else:
                synth = [{
                    "id": f"call_recovered_{i}",
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                } for i, (name, args) in enumerate(recovered)]
                conversation.append({"role": "assistant", "content": None, "tool_calls": synth})
                calls = [(c["id"], c["function"]["name"], c["function"]["arguments"])
                         for c in synth]

            # Run every call and append a tool response for EACH id — even on an
            # unexpected error — so the assistant tool_calls message is never left
            # without its matching responses (which would 400 the next API call).
            for call_id, tool_name, raw_args in calls:
                try:
                    args = json.loads(raw_args or "{}")
                except (json.JSONDecodeError, TypeError):
                    args = {}
                result = run_tool(tool_name, args)
                conversation.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })
    except Exception as e:
        # Something went wrong this turn — restore the clean pre-turn history so
        # the next message isn't poisoned, and tell the user plainly.
        conversation[:] = snapshot
        _save_session(session_id, sess["uses_vision"], conversation)
        return {"reply": "Sorry — I hit a problem this turn and reset it so "
                         "nothing was left in a broken state. Please try again. "
                         f"(details: {e})"}

    # Exhausted the tool-round cap — return whatever the last message held.
    _save_session(session_id, sess["uses_vision"], conversation)
    return {"reply": strip_tool_markup(message.content if message else None)
            or "Sorry, I got stuck. Please try again."}
