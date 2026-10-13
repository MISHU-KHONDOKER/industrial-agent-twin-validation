# Roadmap: validating an industrial AI agent

## The target

> **Prove, with evidence, that my industrial AI agent is correct, safe,
> efficient and deployable, and show how I proved it.**

The agent is an AI co-pilot that operates a real slide scanner: it guides
operators, drives scans, changes settings, places focus points and repairs
configurations. It already works on production hardware. This roadmap is the
engineering work that turns "it works" into **"here is the evidence that it
works, where it fails, and why it is safe to use"**.

The work is split into milestones. Each one has a single deliverable and a
"done when" test, so progress is never vague.

**Status:** ⬜ not started · ⏳ in progress · ✅ done

---

## Milestones

| # | Milestone | Deliverable | Done when | Skill | Status |
|---|---|---|---|---|---|
| M1 | **Define "correct"** | [Requirements, acceptance criteria and a failure-mode catalogue](docs/M1_definition_of_correct.md) built from 30 real incidents | Every machine action has a written pass/fail rule | Requirement & outcome definition | ✅ |
| M2 | **Test foundation** | [Unit tests for every part that does not use the LLM](docs/M2_test_foundation.md); CI running the tests and the leak check on every push | Tests pass in CI, badge on the README | Production software engineering | ✅ |
| M3 | **Virtual instrument** | [A simulated machine with settings, modes, a licence key and switchable faults](docs/M3_virtual_instrument.md), driven by the real, unchanged co-pilot | Every catalogued *machine-behaviour* fault can be reproduced on demand ([first runs](docs/m3_first_runs.md)) | Simulation, digital twin | ✅ |
| M4 | **Evaluation suite** | [Scenarios run automatically and repeatedly](docs/M4_evaluation_suite.md), on the virtual instrument and on the real scanner | One command reports success rate, time, cost, unsafe actions and false "done" claims ([official results](docs/m4_results.md): 139/140, 0 unsafe; confirmed on the real scanner) | AI evaluation & benchmarking | ✅ |
| M5 | **Large vs small models** | The same suite run on a large hosted model and on small local models | A results table with an evidence-based recommendation | Model selection, cost trade-offs | ⬜ |
| M6 | **Safety & hallucination testing** | Red-team tests: prompt injection, misleading machine responses, unsafe requests | Measured refusal and failure rates, each with a fix or a documented limit | Responsible AI, red-teaming | ⬜ |
| M7 | **Observability** | Tracing and structured logs: one ID follows a request from chat to model to tool to machine | Any failure can be explained from the trace alone | Traceability, LLMOps | ⬜ |
| M8 | **Deployment** | Docker image, a small local model on modest hardware, versioned prompts and models | A fresh machine runs it with one command | Edge AI, MLOps | ⬜ |
| M9 | **Risk & compliance** | Risk register, EU AI Act classification, outline of a technical file | Every risk links to a test from M4–M6 | AI risk assessment, compliance | ⬜ |
| M10 | **Tell the story** | Case study, a one-page summary for decision makers, an article or talk | A non-technical reader understands the trade-offs | Stakeholder communication | ⬜ |
| M11 | *Optional:* **slide-type vision benchmark** | Small vision model vs a vision LLM on public pathology datasets | Accuracy, speed and memory table | Vision, edge inference | ⬜ |

## Why this order

- You cannot evaluate (M4) before defining what correct means (M1) and having
  something safe to test on (M3).
- Model comparisons (M5) and safety tests (M6) reuse the evaluation suite.
- The risk register (M9) is only credible once real, measured failures exist
  to point to.
- The story (M10) is written last, from evidence rather than claims.

## Ground rules

- **No secrets, ever:** API keys, licence/security keys, passwords and `.env`
  files never reach this repository; [`tools/leak_check.py`](tools/leak_check.py)
  enforces it on every commit and push.
- **No personal data:** scan images or results that could belong to a patient
  or customer are never published.
- **Evidence over claims:** every number published here comes from a run that
  can be repeated.
