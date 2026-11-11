# M7 — Observability

**Status:** ✅ done (2026-11-11) · **Scope:** the evaluation path on the virtual scanner

| Result | Evidence |
|---|---|
| Valid, explanatory traces | **5/5**: normal scan, unsafe second scan, missing escalation code, recovered model exception, tool failure |
| Instrumentation behavior check | Tracing on/off produced identical transcripts, model calls, tool calls, machine actions, settings, and scan region |
| Unit tests | **6** covering correlation, redaction, exceptions, blocked dispatch, interleaved requests, and corruption detection |
| Model API or real scanner needed | **No** |

One request ID now follows each start/chat turn through its model calls, tool dispatch,
virtual-machine actions, and final evaluation. A trace is a chronological JSON Lines
file, flushed after every event so an interrupted run leaves its evidence behind.

## 1. How it works

| Part | Responsibility |
|---|---|
| [`evaluation/tracing.py`](../evaluation/tracing.py) | Request/span contexts, unique IDs, UTC timestamps, event sequence numbers, JSONL writes, redaction, validation, and formatting |
| [`evaluation/driver.py`](../evaluation/driver.py) | Wraps the existing model client and tool dispatcher; assigns request IDs and converts twin log deltas into machine events |
| M4/M5/M6 runners | Append the scenario verdict, safety flags, and failed checks to the run's trace |
| [`tools/m7_trace.py`](../tools/m7_trace.py) | Validate and print one complete trace, or one selected request |
| [`tools/m7_trace_check.py`](../tools/m7_trace_check.py) | Generate and check five normal/failure traces with a stand-in model, then compare tracing on/off behavior |

The co-pilot itself is not changed. The evaluator observes its existing external
boundaries: session creation, model calls, `_run_tool_by_name`, and the twin's machine
log. Each machine action belongs to the tool call and request that caused it. A model
request for a tool that never reaches the dispatcher produces `tool_not_dispatched`
rather than disappearing from the evidence.

Every event carries `schema_version`, `trace_id`, `sequence`, `timestamp`, and `event`.
Events inside a user turn also carry `request_id`, `session_id`, and `turn`. Model and
tool spans add their own call IDs, duration, status, and whitelisted result metadata.
Run-level `evaluation_scored` events record the verdict and scorer reasons.

## 2. Failure proof

The free end-to-end check drives the frozen co-pilot through these cases:

| Case | What the trace alone shows |
|---|---|
| Normal scan | Chat → model → tool → machine actions → completed chat → passing evaluation |
| Unsafe second scan | Two `StartScan` machine actions and the final `unsafe=true` verdict; F40 is explained, not fixed |
| Missing escalation code | A completed conversation with no scan and `correct_escalation=false`, including the missing-code failed check; F39 is explained, not fixed |
| Recovered model exception | `model_failed` with the exception type, followed by the co-pilot's recovered `chat_completed` |
| Tool failure | The configuration-refusal tool result with `ok=false` and support code `CONFIG`, followed by the failed evaluation |

The validator rejects missing or crossed request IDs, duplicate or missing terminal
events, non-contiguous sequences, and orphaned model, tool, or machine events.

## 3. Privacy and storage

Traces are written below `evaluation/results/traces/`, which is already gitignored.
They contain no user messages, model prompts or replies, images, credentials,
configuration contents, sample IDs, or raw scanner text. Tool arguments and machine
details use allowlists; for example, slide numbers and scan-box coordinates remain,
while paths and sample IDs are omitted. Exceptions are represented by type, not their
possibly sensitive message. Raw conversations remain in separate local result files.

Public documentation contains numeric results and sanitized event names only. The
usual repository leak check still applies to every committed file.

## 4. Reproduce

Run the unit tests:

```bash
venv/Scripts/python -m pytest tests/test_m7_tracing.py -q
```

Generate and validate all five traces with the frozen co-pilot, without model calls:

```bash
venv/Scripts/python tools/m7_trace_check.py "<frozen-copilot>"
```

Inspect a trace printed by that command, optionally selecting one request:

```bash
venv/Scripts/python tools/m7_trace.py evaluation/results/traces/<trace-id>.jsonl
venv/Scripts/python tools/m7_trace.py evaluation/results/traces/<trace-id>.jsonl \
  --request <request-id>
```

For a deterministic instrumentation A/B check, `run_conversation(..., trace_dir=False)`
disables tracing. The end-to-end check uses this to compare behavior with tracing on
and off. Normal M4–M6 runs trace by default.

## 5. Boundaries

M7 instruments the **evaluation path**, not the production FastAPI server. It adds no
OpenTelemetry dependency, collector, dashboard, or production deployment. Those are
separate deployment concerns. The existing M6 release gate remains failed; this
milestone makes F39/F40 and other evaluated failures inspectable without changing
their measured outcomes.
