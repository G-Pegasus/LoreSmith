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
"""已知的 LLM 服务提供商类型"""

KNOWN_ROLES = {"coordinator", "architect", "writer", "editor", "rewrite", "supervisor"}
"""系统支持的角色类型"""


@dataclass
class ProviderConfig:
    """
    服务提供商配置
    
    定义单个 LLM 服务提供商的配置信息。
    """
    type: str = ""                  # 提供商类型（如 openai, anthropic）
    api_key: str = ""               # API 密钥
    base_url: str = ""              # 自定义 API 基础 URL
    models: list[str] = field(default_factory=list)  # 支持的模型列表

    def requires_api_key(self, name: str) -> bool:
        """判断是否需要 API 密钥"""
        if name in {"ollama", "bedrock"}:
            return False
        if self.type:
            return False
        return True


@dataclass
class ModelRef:
    """
    模型引用
    
    用于引用特定提供商的特定模型，支持回退配置。
    """
    provider: str = ""  # 提供商名称
    model: str = ""     # 模型名称


@dataclass
class RoleConfig:
    """
    角色配置
    
    定义系统中各个角色（coordinator/architect/writer/editor）使用的模型配置。
    支持多模型回退策略。
    """
    provider: str = ""             # 默认提供商
    model: str = ""                # 默认模型
    fallbacks: list[ModelRef] = field(default_factory=list)  # 回退模型列表


@dataclass
class Config:
    """
    系统主配置
    
    包含小说创作系统的所有配置项，包括：
    - 输出目录配置
    - 默认提供商和模型
    - 多提供商配置
    - 角色配置（支持不同角色使用不同模型）
    - 写作风格和上下文窗口大小
    """
    output_dir: str = ""                           # 输出目录
    provider: str = ""                             # 默认提供商
    model: str = ""                                # 默认模型
    providers: dict[str, ProviderConfig] = field(default_factory=dict)  # 提供商配置字典
    roles: dict[str, RoleConfig] = field(default_factory=dict)          # 角色配置字典
    style: str = "default"                         # 写作风格
    context_window: int = 128000                   # 上下文窗口大小（token）

    def fill_defaults(self) -> None:
        """填充默认值"""
        if not self.output_dir:
            self.output_dir = str(Path("output") / "novel")
        if not self.style:
            self.style = "default"
        if self.context_window <= 0:
            self.context_window = 128000

    def validate_base(self) -> None:
        """验证基本配置的有效性"""
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
        """验证模型引用的有效性"""
        if not ref.provider or not ref.model:
            raise ValueError(f"{owner} must have both provider and model")
        pc = self.providers.get(ref.provider)
        if pc is None:
            raise ValueError(f'{owner} references provider "{ref.provider}" which is not configured')
        if pc.requires_api_key(ref.provider) and not pc.api_key:
            raise ValueError(f'{owner} references provider "{ref.provider}" which has no api_key')

    def candidate_models(self, provider: str) -> list[str]:
        """获取指定提供商的候选模型列表"""
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
