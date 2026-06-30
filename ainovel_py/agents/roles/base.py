from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable

from ainovel_py.agents.context_manager import ContextManager
from ainovel_py.agents.llm_client import OpenAICompatClient
from ainovel_py.agents.runner import AgentRunner
from ainovel_py.assets import AssetBundle
from ainovel_py.bootstrap.config import Config
from ainovel_py.store.store import Store


class BaseAgent(ABC):
    name: str = ""

    def __init__(
        self,
        cfg: Config,
        runner: AgentRunner,
        store: Store,
        assets: AssetBundle,
        emit_event: Callable[[Any], None],
        emit_stream: Callable[[str, str], None],
    ) -> None:
        self.cfg = cfg
        self.runner = runner
        self.store = store
        self.assets = assets
        self.emit_event = emit_event
        self.emit_stream = emit_stream
        self.context_manager = ContextManager(context_window=cfg.context_window)

    @abstractmethod
    def system_prompt(self) -> str: ...

    @abstractmethod
    def execute(self, **kwargs) -> dict[str, Any]: ...

    def build_client(self) -> OpenAICompatClient:
        # 优先查找角色专属配置（cfg.roles[name]），无则回退全局默认
        role_cfg = self.cfg.roles.get(self.name)
        if role_cfg and role_cfg.provider and role_cfg.model:
            provider_name = role_cfg.provider
            model_name = role_cfg.model
        else:
            provider_name = self.cfg.provider
            model_name = self.cfg.model

        pc = self.cfg.providers.get(provider_name)
        if pc is None or not pc.api_key:
            raise RuntimeError(f"provider {provider_name} api_key 未配置")
        key_norm = pc.api_key.strip().lower()
        if key_norm in {"dummy-key", "dummy", "test", "placeholder", "changeme"}:
            raise RuntimeError(f"provider {provider_name} api_key 为占位值")
        return OpenAICompatClient(
            api_key=pc.api_key,
            model=model_name,
            base_url=pc.base_url,
            timeout=120.0,
        )
