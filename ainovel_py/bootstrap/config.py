from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


KNOWN_PROVIDER_TYPES = {
    "openai",
    "anthropic",
    "gemini",
    "openrouter",
    "deepseek",
    "qwen",
    "glm",
    "grok",
    "ollama",
    "bedrock",
}

KNOWN_ROLES = {"coordinator", "architect", "writer", "editor"}


@dataclass
class ProviderConfig:
    type: str = ""
    api_key: str = ""
    base_url: str = ""
    models: list[str] = field(default_factory=list)

    def requires_api_key(self, name: str) -> bool:
        if name in {"ollama", "bedrock"}:
            return False
        if self.type:
            return False
        return True


@dataclass
class ModelRef:
    provider: str = ""
    model: str = ""


@dataclass
class RoleConfig:
    provider: str = ""
    model: str = ""
    fallbacks: list[ModelRef] = field(default_factory=list)


@dataclass
class Config:
    output_dir: str = ""
    provider: str = ""
    model: str = ""
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    roles: dict[str, RoleConfig] = field(default_factory=dict)
    style: str = "default"
    context_window: int = 128000

    def fill_defaults(self) -> None:
        if not self.output_dir:
            self.output_dir = str(Path("output") / "novel")
        if not self.style:
            self.style = "default"
        if self.context_window <= 0:
            self.context_window = 128000

    def validate_base(self) -> None:
        if not self.provider:
            raise ValueError("provider is required")
        if not self.model:
            raise ValueError("model is required")
        pc = self.providers.get(self.provider)
        if pc is None:
            raise ValueError(f'provider "{self.provider}" is not configured in providers')
        if pc.requires_api_key(self.provider) and not pc.api_key:
            raise ValueError(f'provider "{self.provider}" has no api_key configured')

        for role, rc in self.roles.items():
            if role not in KNOWN_ROLES:
                raise ValueError(f'unknown role "{role}" in roles config')
            if not rc.provider or not rc.model:
                raise ValueError(f'role "{role}" must have both provider and model')
            self._validate_model_ref(f'role "{role}"', ModelRef(provider=rc.provider, model=rc.model))
            for idx, fb in enumerate(rc.fallbacks):
                self._validate_model_ref(f'role "{role}" fallback[{idx}]', fb)

    def _validate_model_ref(self, owner: str, ref: ModelRef) -> None:
        if not ref.provider or not ref.model:
            raise ValueError(f"{owner} must have both provider and model")
        pc = self.providers.get(ref.provider)
        if pc is None:
            raise ValueError(f'{owner} references provider "{ref.provider}" which is not configured')
        if pc.requires_api_key(ref.provider) and not pc.api_key:
            raise ValueError(f'{owner} references provider "{ref.provider}" which has no api_key')

    def candidate_models(self, provider: str) -> list[str]:
        if not provider:
            return []
        seen: set[str] = set()
        out: list[str] = []

        def add(model_name: str) -> None:
            m = model_name.strip()
            if not m or m in seen:
                return
            seen.add(m)
            out.append(m)

        pc = self.providers.get(provider)
        if pc:
            for m in pc.models:
                add(m)
        if self.provider == provider:
            add(self.model)
        for rc in self.roles.values():
            if rc.provider == provider:
                add(rc.model)
            for fb in rc.fallbacks:
                if fb.provider == provider:
                    add(fb.model)
        return out


def provider_config_from_dict(data: dict[str, Any]) -> ProviderConfig:
    return ProviderConfig(
        type=str(data.get("type", "") or ""),
        api_key=str(data.get("api_key", "") or ""),
        base_url=str(data.get("base_url", "") or ""),
        models=[str(x) for x in data.get("models", []) if str(x).strip()],
    )


def role_config_from_dict(data: dict[str, Any]) -> RoleConfig:
    fallbacks_raw = data.get("fallbacks", []) or []
    fallbacks = [
        ModelRef(provider=str(x.get("provider", "") or ""), model=str(x.get("model", "") or ""))
        for x in fallbacks_raw
        if isinstance(x, dict)
    ]
    return RoleConfig(
        provider=str(data.get("provider", "") or ""),
        model=str(data.get("model", "") or ""),
        fallbacks=fallbacks,
    )
