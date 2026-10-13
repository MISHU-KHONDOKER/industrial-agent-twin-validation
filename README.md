# Industrial AI Agent Validation on a Digital Twin

[![tests](https://github.com/MISHU-KHONDOKER/industrial-agent-twin-validation/actions/workflows/tests.yml/badge.svg)](https://github.com/MISHU-KHONDOKER/industrial-agent-twin-validation/actions/workflows/tests.yml)

An **industrial AI agent** — an LLM co-pilot that operates a laboratory slide scanner
for its users — and the **evidence** that it is correct, safe and deployable.

The agent is validated on a **behavioural digital twin** of the instrument: a virtual
scanner built only from observed real behaviour (every behaviour is listed with where
and when it was seen), with real failures that can be switched on. On it, the **real,
unchanged agent** is tested without a language model and with the real model in the
loop — and every result is shown with the real terminal output.

### Key results

| | |
|---|---|
| **139 / 140** | customer conversations correct with the real language model in the loop (official run, 14 scenarios × 10) |
| **0 · 0 · 0** | unsafe machine actions · false "success" claims · false "failure" claims |
| **Twin ⇄ real** | on the real scanner the agent did what the twin predicted — and caught a real machine fault live, exactly as proven in simulation |
| **6 defects** | found by the evaluation (3 on the twin, 3 on the real scanner) and fixed — the twin ones proven by switching the fix off on purpose |
| **≈ ¥0.01** | per customer conversation (98 % of the prompt served from cache) |
| **120 tests** | in CI on every push, with a leak check and a mutation test |

| Milestone | What it proves |
|---|---|
| [M1](docs/M1_definition_of_correct.md) Define "correct" | 12 rules, pass/fail criteria for every machine action, 32 real failure modes |
| [M2](docs/M2_test_foundation.md) Test foundation | Unit tests + CI + a mutation-test proof |
| [M3](docs/M3_virtual_instrument.md) Digital twin | 16 of 16 scenarios with the real agent, each fix proven by breaking it on purpose |
| [M4](docs/M4_evaluation_suite.md) Evaluation suite ✅ | Real model in the loop, 280 scored conversations, confirmed on the real scanner |

> **What this is not:** the full scanner integration. That lives in a private
> repository, because it controls a proprietary hardware interface and embeds
> vendor documentation.

---

## About me and the full project

I'm **Mohyminul Islam** (Mishu), an AI/ML engineer working toward
**Industrial AI Application Engineer** roles: AI systems for industrial machines,
built so they can be checked, measured and trusted.

- **M.S. in Software Engineering**, Northwestern Polytechnical University,
  Xi'an, China. Thesis on protocol-aware GANs for network intrusion detection.
- **First-author publications:** an IEEE conference paper (ICCBDAI 2025,
  *Best Oral Presentation Award*) and a journal paper in *Expert Systems*
  (Wiley, SCI), with a second journal paper submitted to Springer Nature.
  State-of-the-art F1 on CICIDS2017, UNSW-NB15 and NSL-KDD, statistically
  significant against all baselines (p < 0.01).
- **4+ years as a network engineer** at an international telecom gateway:
  alarms, signalling, fault response with vendors and carriers. That is where I
  learned how real machines fail, and how support actually works.
- **B.Sc. in Electronics and Communication Engineering**, East West University,
  Dhaka.
- Other projects: a multi-LLM gateway on Kubernetes with Prometheus/Grafana
  observability, and a fully offline RAG chatbot (TinyLlama + local embeddings,
  no data leaves the machine).
- Languages: English (fluent), Bengali (native), Mandarin (basic).

**Contact:** sailormishu50@gmail.com

This repository is the public part of a project I build and run on real
hardware: an **AI co-pilot for an industrial slide scanner** (digital
pathology). It started as a troubleshooting chat assistant and now **operates
the machine itself**:

| What the co-pilot does | How |
|---|---|
| Guides operators from power-on to a finished scan, one step at a time, in two languages | LLM + a structured knowledge base of fault cards, built from real support cases and field notes |
| Drives the scanner: starts scans, follows progress, reads back the results | Tool calling over the scanner's own remote-control interface |
| Changes settings that have no remote command | GUI automation of the scanner software, with every change read back |
| Finds the sample on the slide and places its own focus points on the cells | Classic computer vision on the preview image (no extra model needed) |
| "Customer mode": one command checks the configuration against a known-good file, repairs it, scans and reports | An agent pipeline with safety gates at every step |

Running on **two production scanners** (one brightfield, one fluorescence). A
customer-mode scan has been completed end to end on real hardware.

### What I focus on as an engineer

- **Defining "correct" before building:** acceptance criteria, edge cases and
  failure modes for each machine action.
- **Evaluation, not impressions:** repeatable tests that measure success rate,
  time and failure types, and comparisons of large and small models on accuracy,
  latency and cost.
- **Safety and traceability:** an agent that controls a machine must refuse
  rather than guess, and every change it makes must be logged and verified.
- **Learning from real incidents.** Two examples from this project:
  - The agent once applied another machine's known-good configuration, including
    a machine-bound licence key, and the scanner locked itself. I added a guard
    that refuses a configuration from a different machine or a different imaging
    mode before anything is written, and a key that is never copied.
  - The agent reported a perfect scan as failed, because the real machine's
    status code meant the opposite of the simulator's. Success is now decided by
    the actual result files, never by a status number.

### Tested core

The co-pilot's safety-critical logic (configuration guards, result reading,
geometry, focus-point choice, sample finding) is in [`copilot_core/`](copilot_core/)
with 58 unit tests in [`tests/`](tests/), each named after the requirement it
proves. See [M2 — Test foundation](docs/M2_test_foundation.md).

**Proof that the tests work:** [a test that catches a real production incident](docs/demo_mutation_test.md)
— the safety guard is switched off on purpose and the test fails, without touching any machine.

### Virtual instrument

A [virtual scanner](docs/M3_virtual_instrument.md) that the **real, unchanged co-pilot**
drives end to end, with real failures switched on at will (another machine's config,
a scan frozen behind a dialog, a lying status message, scrambled settings). First
result: 11 of 13 scenarios passed, 2 known open failure modes reproduced — including
a false success claim.
Checked by hand in a [seven-step walkthrough](docs/M3_walkthrough.md) with the real
terminal output of every run.

**Three weaknesses fixed and proven on the twin** — each with the fix switched
off on purpose to prove the scenario catches it:
- [the false success claim](docs/demo_s11_fix.md) — real result files checked
  first; they showed the obvious fix would have been wrong;
- [a "look only" tool that quietly changed the machine](docs/demo_s12_fix.md) —
  a real field incident, now an honest refusal;
- [placing a focus point could delete one](docs/demo_s13_fix.md) — a new
  scenario for a real machine behaviour, including the co-pilot deleting its own
  points on a retry.

**New field problem, caught while it happens:** [a scan that keeps starting over
from the first row](docs/M3_virtual_instrument.md#s14-and-s15-added-2026-10-08--a-scan-that-never-ends)
— the detection rule was replayed on 17 recorded real scans first (no false alarm,
both real cases caught), then the co-pilot's stop-fix-rescan was proven on the twin,
including the case where the machine does not confirm the stop.

Now [16 of 16 scenarios pass](docs/m3_first_runs.md).

### Evaluation suite ✅

The [evaluation suite](docs/M4_evaluation_suite.md) puts the **real language model**
in the loop: 14 customer conversations on the virtual scanner — a clean scan, another
machine's settings, a scan that never ends, scrambled settings, an empty slide position,
a frozen dialog, Chinese, the first-batch confirmation and more — each run 10 times and
scored by fixed rules for success, unsafe actions, false claims, escalation, time and cost.

- **Two official measurements: 137/140 and 139/140**, release gate (0 unsafe, 0 false
  success) passed both times.
- **Every failure read by hand.** Most were the scorer's mistakes, fixed only after a
  re-check on every saved reply; the real ones became findings: **scanning without
  asking which slide (F29), an invented support code (F30), corrected settings not told
  (F37)** — each fixed in code and proven by switching the fix off on purpose.
- **Confirmed on the real scanner:** the same scenarios with the same version — the agent
  did what the twin predicted, and when the machine developed a real fault mid-test, the
  agent caught it and handed the one unconfirmed step to a person, exactly as proven in
  simulation.
- **≈ ¥0.01 per conversation**, because 98 % of every prompt is served from cache.

Every step is shown with the real terminal output.

### Publishing safely

Everything here passes [`tools/leak_check.py`](tools/leak_check.py), which runs
on every commit and push. It blocks API keys, licence-style keys, real IP
addresses, configuration files, internal documents and a private list of
company-specific terms. That list is kept off GitHub, because publishing it
would itself be a leak.

### Coming next (public write-ups)

The full plan, with the status of each milestone, is in
**[ROADMAP.md](ROADMAP.md)**. Highlights:

- **Large vs small models (M5):** the same evaluation suite on a large hosted model
  and on small local models — accuracy, safety, latency and cost side by side.
- **Red-teaming (M6):** prompt injection, misleading machine responses and unsafe
  requests, with measured refusal rates.
- A **risk register and EU AI Act assessment** for an AI agent that controls
  laboratory equipment.

---

## What it demonstrates

| Capability | Why it matters |
|---|---|
| **Multi-turn tool-calling loop** | The model requests an action; *your* code runs it, feeds the result back, and repeats until a real answer — not a demo, a real agent loop. |
| **Per-session isolation + SQLite persistence** | Every conversation has its own ID and survives restarts. Fixes the classic "one global list for the whole server" defect. |
| **Crash-safe conversation handling** | A failed turn rolls back to a clean snapshot instead of corrupting history; dangling tool calls self-heal on the next request. |
| **Leaked tool-call recovery** | Some models emit tool calls as plain-text markup instead of the structured field — this parses and re-runs them so a leak becomes a real action, never visible junk. |
| **Safety-first design** | Tools only run when the model explicitly calls them; a tool error can never crash the chat; nothing is invented. |

---

## Architecture

```
Browser (index.html)
   │  fetch /api/start, /api/chat, /api/session/{id}
   ▼
FastAPI (app/main.py)
   │  session lookup → SQLite (copilot.db)
   │  tool loop → OpenAI-compatible API (DeepSeek by default)
   ▼
run_tool()  ← your domain actions plug in here
```

- `app/main.py` — the agent: tool loop, session storage, crash recovery.
- `app/static/index.html` — a minimal chat front-end.
- `knowledge/system_prompt.md` — placeholder system prompt (swap in your own).
- `.env.example` — configuration template (copy to `.env`).

---

## Running it

### 1. Set up a virtual environment

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
pip install -r requirements.txt
```

### 3. Configure your API key

```powershell
Copy-Item .env.example .env
# edit .env and set DEEPSEEK_API_KEY (or point DEEPSEEK_BASE_URL at another provider)
```

### 4. Start the server

```powershell
uvicorn app.main:app --reload --port 8000
```

### 5. Open the app

Browse to **http://127.0.0.1:8000/** and try:

- *"What's the current time?"* — exercises the `current_time` tool.
- *"Add 12 and 30"* — exercises the `add_numbers` tool.

---

## Adapting it to your own domain

The tool loop is domain-agnostic. To build your own agent:

1. **Define your tools** — replace the `TOOLS` list in `app/main.py` with your
   own function schemas (actions, read-only queries, anything).
2. **Implement `run_tool()`** — dispatch each tool name to your integration.
   Keep the "never raise, always return a safe dict" contract.
3. **Replace the knowledge base** — swap `knowledge/system_prompt.md` for your
   domain instructions, or move to retrieval (RAG) once the content outgrows
   "stuff everything into the prompt".

---

## Design notes (things I learned the hard way)

- **`uvicorn --reload` only watches `.py` files.** Editing knowledge/content
  files needs a manual restart.
- **Conversation memory belongs on the server, not the browser.** A refresh
  should never start a new conversation; only an explicit "new conversation"
  should.
- **A tool call must always get a tool response**, even on error — otherwise
  the API rejects the whole next request with `tool_calls must be followed by
  tool messages`.
- **Snapshot before you mutate shared state.** If a turn fails mid-loop, roll
  back rather than leave a dangling assistant message behind.

---

## License

MIT — see [LICENSE](LICENSE).
