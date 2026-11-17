# M8 — Deployment

**Status:** ✅ done · **Scope:** the public FastAPI reference agent with a local model

> **Release gate:** M6 remains **failed** (109/120, F39 escalation weakness and F40 unsafe
> rescan). This local deployment is an offline demonstration, not approval for production
> scanner operation. The proprietary scanner integration is not part of this image.

## 1. Deployment contract

A fresh machine with Docker Engine and Docker Compose should need only:

```bash
docker compose up --build
```

The first run downloads the Ollama runtime and approximately 2.5 GB of model weights. Open
**http://127.0.0.1:8000/** after the application health check passes. Later runs reuse the
model and conversation volumes.

The deployment consists of:

| Part | Responsibility |
|---|---|
| `ollama` | Serves the local, OpenAI-compatible model endpoint; no inbound host port is published |
| `model-init` | Pulls the exact configured model tag and must succeed before the app starts |
| `app` | Runs the unchanged agent loop as a non-root user, with SQLite on a persistent volume |
| `deployment/manifest.json` | Records the prompt SHA-256, model tag and weight digest, and runtime version |

Only the app's loopback port is published. Model and conversation data survive container
recreation in the named volumes `ollama-models` and `copilot-data`. No hosted API key is
needed for this profile.

## 2. Version policy

The local model is `qwen3:4b-instruct-2507-q4_K_M`: a dated Qwen3 4B instruct tag with
Q4_K_M quantization. The manifest also records the model weight layer's SHA-256 from the
public Ollama registry. Ollama itself is pinned to `ollama/ollama:0.13.3`; Python application
dependencies remain exactly pinned in `requirements.txt`.

The app hashes `knowledge/system_prompt.md` at startup. A prompt edit without the matching
manifest update stops startup rather than silently running an unrecorded prompt. In the local
profile, selecting any model other than the manifest's model also stops startup.

Query `GET /api/version` to inspect the active profile, model and prompt hash. `GET /health`
is the container liveness/readiness endpoint; it does not make an expensive inference call.

M5 provides the model-selection evidence: Qwen3 4B was the best small model tested, at 21/28
correct with zero unsafe actions and zero false claims, but averaged 268 seconds per
conversation on the 32 GB CPU-only test PC. The dated deployment tag is separately pinned for
reproducibility; it must not be represented as a new M5 correctness result without rerunning
the suite.

## 3. Resource and safety boundaries

Allow several GB of free disk space for the runtime and model. 16 GB RAM is a practical
recommendation, not a measured minimum; the M5 evidence comes from a 32 GB machine. CPU
inference can take minutes, and no production latency or safety claim follows from a healthy
container.

This profile deliberately contains only the public tools (`current_time` and `add_numbers`).
It cannot operate the real scanner. F39/F40 remain visible and unresolved; containerization
changes neither the M6 result nor the release decision.

## 4. Verification

Verification on the development PC, with the Docker launch completed on 2026-11-17:

| Check | Result |
|---|---|
| M8 manifest, model guard and Compose structure tests | **4/4 passed** |
| Full unit suite | **184 passed, 1 expected xfail** (known open F20) |
| Compose validation, image build and one-command launch | **Passed** with Docker Engine 29.9.3 and Compose v5.7.0; model initialization exited 0 and both long-running services became healthy |
| Containerized web/API + local Qwen3 4B conversation | **Passed**: `/`, health, version, start and chat returned 200; addition answer 42 |
| SQLite persistence across `docker compose restart app` | **Passed**: the same session returned 200 with its complete conversation after restart |
| `git diff --check` | **Clean** |

The fresh container/volume launch downloaded the pinned runtime and exact model tag, then ran
the web chat entirely through Docker. Earlier direct FastAPI verification used the same model
tag and a temporary SQLite database. These checks verify deployment and persistence, not a new
model correctness, safety or latency result.

Useful checks:

```bash
python -m pytest tests/test_m8_deployment.py -q
python tools/leak_check.py --tree HEAD
docker compose config
docker compose up --build
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/version
```

Stop with `docker compose down`. Keep the named volumes to preserve the model and sessions;
`docker compose down --volumes` deletes both and is intentionally not part of normal shutdown.
