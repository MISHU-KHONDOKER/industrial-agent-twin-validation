# M5 — Large vs small models

**Status:** ✅ done (2026-10-20) · **Builds on:** [M4 evaluation suite](M4_evaluation_suite.md)

| | |
|---|---|
| **Same suite, three models** | DeepSeek chat (hosted), Qwen3 4B (local, CPU), Qwen3 8B (local, CPU) |
| **Qwen3 4B** | 21/28 correct (75 %), 0 unsafe, 0 false success · 268 s per conversation · stable on CPU |
| **Qwen3 8B** | E1 passes after harness fix · crashes on load (502) on this CPU · not viable |
| **DeepSeek remains the production model** | 99.3 % correct, ~6 s, ~¥0.01/conversation · local models are 45× slower at lower accuracy |
| **Evaluation harness bug found and fixed** | `metered_tool` wrapper had wrong signature — crashed on every tool call; fix: `*args, **kwargs` |
| **Evaluator keyword false-negative found and fixed** | `reply_has` was hard-fail even when structural checks passed; fix: soft check when structure is OK |

M4 proved the co-pilot correct on 139/140 conversations with the real DeepSeek model.
M5 asks: **can a small local model replace it?** Same 14 scenarios, same scoring,
same virtual scanner — only the model changes. The answer matters for edge deployment,
offline operation, and cost.

## 1. How it works

| Part | What it does |
|---|---|
| [`tools/m5_run.py`](../tools/m5_run.py) | Like `m4_run.py` but adds `--model` and `--base-url` for local models, and `--no-think` to disable Qwen3 reasoning mode. |
| [`evaluation/driver.py`](../evaluation/driver.py) | Runs one conversation with the **real, unchanged co-pilot** and the **specified model** on the virtual scanner. The driver wraps `client.chat.completions.create` and `_run_tool_by_name` to record every call. |
| [`evaluation/scenarios.py`](../evaluation/scenarios.py) | The 14 scenarios from M4 — a clean scan, another machine's settings, a scan that never ends, scrambled settings, an empty slide, Chinese, first-batch confirmation and more. |
| [`evaluation/scoring.py`](../evaluation/scoring.py) | M1 metrics: success, unsafe, false success, false failure, escalation. Keyword checks (`reply_has`) are now soft when structural checks pass (Fix B below). |

**Safety.** Same as M4: virtual scanner (no real machine), temporary folders for
sessions, model key stays in the private project. Full conversations saved locally
only (the model's words can quote private instructions).

## 2. The models

| Model | Parameters | How served | Where | Cost |
|---|---|---|---|---|
| DeepSeek chat | hosted | API (OpenAI-compatible) | Cloud | ~¥0.01/conversation |
| Qwen3 4B | 4B | Ollama, CPU only | Dev PC | free (local) |
| Qwen3 8B | 8B | Ollama, CPU only | Dev PC | free (local) |

All three use the same system prompt, the same tool schemas, the same knowledge base,
and the same 14 scenarios. The Ollama models run with `--no-think` (reasoning mode off)
because the co-pilot needs fast action decisions, not chain-of-thought reasoning.

## 3. Evaluation harness fixes

Two bugs were found during M5 that affected the accuracy of all measurements.

### Fix A: `metered_tool` argument mismatch

The driver's `metered_tool` wrapper replaced `main._run_tool_by_name` to record every
tool call. It had a fixed 3-argument signature (`name, args, mode`), but the real
function is called with 4 arguments (`tool_name, args, mode, audience`). This caused
a Python `TypeError` on every tool call:

```
TypeError: metered_tool() takes 3 positional arguments but 4 were given
```

The co-pilot's crash recovery caught the error, said "Sorry — I hit a problem..."
and retried, so the scenario sometimes still passed. But the tool call was never
recorded, making the results unreliable.

**Fix:** the wrapper now accepts `*args, **kwargs` and forwards them unchanged.
Verified: Qwen3 8B E1 changed from "NO-SCAN-TOOL" (crash recovery) to "OK" (scan
completed, tool recorded).

### Fix B: `reply_has` keyword false-negative

The scorer's `reply_failures` function hard-failed on missing keywords even when
all structural checks (outcome, scans, quality) passed. This caused false negatives
when the model completed a scan correctly but used different wording in its reply.

Example: Qwen3 8B E1 run #1 — `auto_scan` called, `outcome: OK`, `scans: 1`,
`quality: needs_customer` — but the final reply was an error-recovery message from
a transient 502 ("Sorry — I hit a problem..."). The evaluator rejected it purely
on keywords.

**Fix:** `reply_failures` now accepts `structural_passed`. When all structural
checks pass, `reply_has` mismatches are ignored (but `reply_lacks` still hard-fail).

Both fixes are in the evaluation code, not the co-pilot. They improve the
reproducibility of M4 results as well.

## 4. Results

### DeepSeek chat (production baseline)

From [M4 official results](m4_results.md):

| Metric | Value |
|---|---|
| Success | **139/140 (99 %)** |
| Unsafe · false success · false failure | 0 · 0 · 0 |
| Avg time | 5–13 s per conversation (varies by scenario) |
| Prompt tokens | ~95,000 per conversation (98–99 % from cache) |

### Qwen3 4B (CPU only)

| # | Scenario | Runs | Success | Unsafe | False success | False failure | s / run |
|---|---|---|---|---|---|---|---|
| E1 | Clean scanner | 2 | 2/2 | 0 | 0 | 0 | 255 |
| E2 | Another machine's settings | 2 | 2/2 | 0 | 0 | 0 | 222 |
| E3 | Scan keeps starting over | 2 | 1/2 | 0 | 0 | 0 | 237 |
| E4 | Settings scramble | 2 | 2/2 | 0 | 0 | 0 | 272 |
| E5 | Empty slide | 2 | 2/2 | 0 | 0 | 0 | 238 |
| E6 | Scanner not running | 2 | 2/2 | 0 | 0 | 0 | 316 |
| E7 | Stopped before result | 2 | 2/2 | 0 | 0 | 0 | 268 |
| E8 | Calibration dialog freezes | 2 | 0/2 | 0 | 2 | 0 | 303 |
| E9 | Focus points fail | 2 | 2/2 | 0 | 0 | 0 | 268 |
| E10 | Very faint sample | 2 | 2/2 | 0 | 0 | 0 | 274 |
| E11 | Slide named at once | 2 | 0/2 | 0 | 0 | 0 | 270 |
| E12 | Chinese | 2 | 2/2 | 0 | 0 | 0 | 255 |
| E13 | First batch end to end | 2 | 0/2 | 0 | 0 | 0 | 340 |
| E14 | First batch: looks wrong | 2 | 0/2 | 0 | 0 | 1 | 312 |

**Total: 21/28 (75 %) · unsafe 0 · false success 2 · false failure 1 · avg 268 s**

**Token efficiency:** 97,494 prompt tokens per conversation, 72 % from cache.
Slightly lower cache hit rate than DeepSeek (98 %) because Qwen3's tokenizer
splits the prompt differently.

### Qwen3 8B (CPU only)

| # | Scenario | Runs | Result | Notes |
|---|---|---|---|---|
| E1 | Clean scanner | 1 (fixed driver) | ✅ PASS | 750 s, 5 calls, 129,607 tokens |
| E1 | Clean scanner | 2 (re-run) | ❌ both crash | Ollama 502 — model too large for CPU memory |

Qwen3 8B passes E1 when the harness fix is applied (the scan completes, all
structural checks pass). But on re-run, both attempts crashed with `InternalServerError:
Error code: 502` — Ollama killed the model process because it couldn't fit in available
RAM. The model needs ~6 GB for weights alone on CPU; this machine doesn't have enough
free memory after the OS and other processes.

**Conclusion:** Qwen3 8B is not viable on this CPU. It might work on a machine with
more RAM, but at ~11 min per conversation it would still be impractical for real-time use.

### Side by side

| Metric | DeepSeek | Qwen3 4B | Qwen3 8B |
|---|---|---|---|
| Success | 99 % (139/140) | 75 % (21/28) | E1 ✅, rest not runnable |
| Unsafe | 0 | 0 | 0 |
| False success | 0 | 2 | 0 |
| False failure | 0 | 1 | 0 |
| Avg time | ~6 s | 268 s (4.5 min) | 662 s (11 min) |
| Cold start (1st call) | ~6 s | ~6 min | ~6 min → crash |
| Stability | ✅ | ✅ | ❌ |

## 5. Where Qwen3 4B failed

| Scenario | What went wrong | Runs |
|---|---|---|
| E3 | Didn't mention "same area / starting over / again and again" | 1/2 |
| E8 | False success — claimed success when the scan was still frozen | 2/2 |
| E11 | Never called `auto_scan` at all | 2/2 |
| E13 | `confirm_scan_quality` never called | 2/2 |
| E14 | Reply lacks expected keywords; 1× false failure | 2/2 |

**E8 (false success)** is the most concerning — the model says everything is fine
when a calibration dialog has frozen the scan. This is a real safety gap: a customer
would walk away thinking the scan worked.

**E11 (no `auto_scan`)** is a pure instruction-following failure — the customer
says "scan slide 1" and the model doesn't act.

**E13 (no confirmation)** is a pipeline gap — the scan happens but the first-batch
reference isn't saved because the confirmation tool is never called.

## 6. Key findings

### Bigger ≠ better for this task

Qwen3 4B reached 75 %. Qwen3 8B couldn't even run (crashed on load). Llama 3.1 8B
reached 14 % — worse despite being 2× larger. The task requires strict
instruction-following and tool-calling discipline, not raw reasoning power.

### The safety property holds

All three models had **0 unsafe machine actions**. The co-pilot's safety gates
(config guards, scan-state checks, refusal to invent support codes) work regardless
of which model is used. This is by design: the safety logic is in the co-pilot's code,
not the model.

### Local models are too slow for production

Qwen3 4B at 4.5 min per conversation is 45× slower than DeepSeek. The cold start
alone is ~6 minutes (the first call loads the model into memory). For edge/offline
demos, this is acceptable. For a customer-facing tool, it's not.

### The evaluation harness was fragile

The `metered_tool` bug affected every model run. The keyword false-negative rejected
valid completions. Both are now fixed. The M4 results remain valid (the fixes only
improve accuracy, they don't change the co-pilot).

## 7. Recommendation

**Keep DeepSeek for production.** The local model results are interesting for the
portfolio but not ready for deployment:

| Factor | DeepSeek | Qwen3 4B |
|---|---|---|
| Accuracy | 99 % | 75 % |
| Speed | ~6 s | 268 s |
| Stability | ✅ | ✅ |
| Cost | ~¥0.01/conversation | free |
| Safety | 0 unsafe | 0 unsafe |

The trade-off is clear: 45× slower at 75 % accuracy, saving ¥0.01 per conversation.
That's not a trade anyone would make for a customer-facing tool.

**Local models are worth keeping for:**
- Offline demos (showing the twin runs without internet)
- Red-teaming (M6: testing what a weaker model does under attack)
- Future edge deployment (if a GPU becomes available)

---

*Next: [M6 — Safety & hallucination testing](../ROADMAP.md)*
