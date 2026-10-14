"""M5: the M4 evaluation suite on ANOTHER language model (e.g. a small local one).

Same scenarios, same driver, same scoring as M4 (tools/m4_run.py, unchanged). The
co-pilot is not changed either: its model client is swapped from the OUTSIDE when it
is loaded, so every call it makes goes to the chosen model instead. All models are
tested on the same frozen co-pilot copy (the one DeepSeek's official M4 result was
measured on), so the comparison is fair.

Run with the PRIVATE project's Python (it has the co-pilot's dependencies):

    <private>/venv/Scripts/python tools/m5_run.py --private <co-pilot copy> --model m5-qwen3-4b --scenarios E1 --repeats 1

  --base-url   OpenAI-compatible server (default: local Ollama, http://localhost:11434/v1)
  --model      the model name on that server

Writes evaluation/results/m5_<model>_<time>.json (LOCAL ONLY, gitignored like M4's raw
results: the model's words can quote the private knowledge base). No report yet.
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

from openai import OpenAI  # noqa: E402

import evaluation.driver as driver  # noqa: E402
from evaluation.scenarios import SCENARIOS  # noqa: E402
from evaluation.scoring import score_run  # noqa: E402
from m4_run import aggregate, pct  # noqa: E402

RESULTS_DIR = REPO / "evaluation" / "results"
CALL_TIMEOUT = 1800       # s — a CPU model reading ~25,000 tokens for the first time is slow


def use_model(base_url: str, model: str):
    """Make every co-pilot loaded by the driver talk to `model` on `base_url`."""
    original_load = driver.load_copilot
    client = OpenAI(base_url=base_url, api_key="local", timeout=CALL_TIMEOUT)

    def load_with_model(private_root, twin):
        main = original_load(private_root, twin)

        def create_on_model(*args, **kwargs):
            kwargs["model"] = model          # the co-pilot asks for its own model name
            return client.chat.completions.create(*args, **kwargs)

        # the co-pilot looks up `client` at call time, so this replaces every call
        main.client = SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=create_on_model)))
        return main

    driver.load_copilot = load_with_model


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--private", required=True, help="the frozen co-pilot copy to test")
    ap.add_argument("--model", required=True)
    ap.add_argument("--base-url", default="http://localhost:11434/v1")
    ap.add_argument("--scenarios", default="E1")
    ap.add_argument("--repeats", type=int, default=1)
    args = ap.parse_args()

    use_model(args.base_url, args.model)
    wanted = args.scenarios.split(",")
    chosen = [s for s in SCENARIOS if s["id"] in wanted]
    started = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"M5: model {args.model} — {len(chosen)} scenario(s) x {args.repeats} = "
          f"{len(chosen) * args.repeats} conversation(s)", flush=True)

    raw, all_scores = [], []
    for sc in chosen:
        for i in range(1, args.repeats + 1):
            run = driver.run_conversation(args.private, sc["script"], sc["mode"], faults=sc["faults"],
                                          loaded=sc.get("loaded", ("clear", None, None, None)),
                                          setup=sc.get("setup", ()))
            s = score_run(sc, run)
            all_scores.append(s)
            raw.append({"scenario": sc["id"], "repeat": i, "score": s, "run": driver.summary(run)})
            calls = run["model_calls"]
            flags = [k for k in ("unsafe", "false_success", "false_failure") if s[k]]
            print(f"  {sc['id']} #{i}: {'SUCCESS' if s['success'] else 'FAIL'}"
                  f"{' ' + ','.join(flags).upper() if flags else ''}  {s['seconds']} s, "
                  f"{len(calls)} calls ({', '.join(str(c['seconds']) for c in calls)} s each), "
                  f"{s['prompt_tokens']:,} prompt tokens"
                  f"{'  | ' + '; '.join(s['rule_breaks'] + s['failed_checks']) if not s['success'] else ''}"
                  f"{'  | crashed: ' + run['error'] if run.get('error') else ''}", flush=True)
    total = aggregate(all_scores)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", args.model)
    out = RESULTS_DIR / f"m5_{safe_name}_{datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps({"started": started, "model": args.model, "base_url": args.base_url,
                               "private": args.private, "repeats": args.repeats,
                               "total": total, "runs": raw}, indent=2, ensure_ascii=False, default=str),
                   encoding="utf-8")
    print(f"raw results (local only): {out.relative_to(REPO)}")
    print(f"TOTAL: success {pct(total['success'], total['runs'])}, unsafe {total['unsafe']}, "
          f"false success {total['false_success']}, false failure {total['false_failure']}, "
          f"avg {total['avg_seconds']} s per conversation")


if __name__ == "__main__":
    main()
