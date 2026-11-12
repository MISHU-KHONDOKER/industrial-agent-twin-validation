import hashlib
import json
import re
from pathlib import Path

import pytest

from app.versioning import MANIFEST_PATH, ROOT, load_runtime_version


def test_deployment_manifest_matches_prompt_and_runtime():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    prompt = ROOT / manifest["prompt"]["path"]

    assert hashlib.sha256(prompt.read_bytes()).hexdigest() == manifest["prompt"]["sha256"]
    assert re.fullmatch(r"[0-9a-f]{64}", manifest["model"]["weights_sha256"])
    assert re.fullmatch(r"ollama/ollama:\d+\.\d+\.\d+", manifest["runtime"]["ollama_image"])
    assert manifest["validation"]["m6_release_gate"] == "failed"
    assert manifest["validation"]["open_findings"] == ["F39", "F40"]


def test_local_runtime_reports_exact_model_and_prompt(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "local")
    monkeypatch.setenv("CHAT_MODEL", "qwen3:4b-instruct-2507-q4_K_M")

    version = load_runtime_version()

    assert version["profile"] == "local"
    assert version["model"] == "qwen3:4b-instruct-2507-q4_K_M"
    assert version["model_version"]["weights_sha256"].startswith("85e4a5b7")
    assert len(version["prompt_sha256"]) == 64


def test_local_runtime_rejects_unrecorded_model(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "local")
    monkeypatch.setenv("CHAT_MODEL", "unrecorded-model")

    with pytest.raises(RuntimeError, match="Local profile requires model"):
        load_runtime_version()


def test_compose_pulls_model_before_starting_app():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert 'command: ["ollama pull \\"$$MODEL_ID\\""]' in compose
    assert "condition: service_completed_successfully" in compose
    assert '"127.0.0.1:8000:8000"' in compose
    assert "DB_PATH: /data/copilot.db" in compose
