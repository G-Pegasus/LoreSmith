from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class InternalApiSettings:
    host: str = "127.0.0.1"
    port: int = 8000
    token: str = ""
    registry_path: str = str(Path("output") / "internal_api" / "runs.json")


def load_settings() -> InternalApiSettings:
    host = os.environ.get("AINOVEL_INTERNAL_API_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port_raw = os.environ.get("AINOVEL_INTERNAL_API_PORT", "8000").strip() or "8000"
    token = os.environ.get("AINOVEL_INTERNAL_API_TOKEN", "").strip()
    registry_path = os.environ.get("AINOVEL_INTERNAL_API_REGISTRY", "").strip() or str(Path("output") / "internal_api" / "runs.json")
    try:
        port = int(port_raw)
    except ValueError:
        port = 8000
    return InternalApiSettings(host=host, port=port, token=token, registry_path=registry_path)
