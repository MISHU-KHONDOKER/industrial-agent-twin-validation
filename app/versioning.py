import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "deployment" / "manifest.json"


def load_runtime_version(manifest_path: Path = MANIFEST_PATH) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    prompt = manifest["prompt"]
    prompt_path = manifest_path.parent.parent / prompt["path"]
    prompt_sha256 = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
    if prompt_sha256 != prompt["sha256"]:
        raise RuntimeError(
            "System prompt does not match deployment/manifest.json; "
            "review the change and update the recorded SHA-256."
        )

    profile = os.getenv("DEPLOYMENT_PROFILE", "external")
    selected_model = os.getenv("CHAT_MODEL", "deepseek-chat")
    expected_model = manifest["model"]["reference"]
    if profile == "local" and selected_model != expected_model:
        raise RuntimeError(
            f"Local profile requires model {expected_model!r}, got {selected_model!r}."
        )

    return {
        "deployment": manifest["deployment"],
        "profile": profile,
        "model": selected_model,
        "model_version": manifest["model"] if profile == "local" else None,
        "prompt_sha256": prompt_sha256,
        "m6_release_gate": manifest["validation"]["m6_release_gate"],
        "open_findings": manifest["validation"]["open_findings"],
    }
