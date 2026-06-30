"""Per-Agent LLM 配置测试。

验证 BaseAgent.build_client() 能正确读取角色专属配置并回退到全局默认。
"""
from __future__ import annotations

import pytest

from ainovel_py.agents.roles.base import BaseAgent
from ainovel_py.bootstrap.config import Config, ProviderConfig, RoleConfig


class _DummyAgent(BaseAgent):
    """测试用具象子类。"""
    name = "test_role"

    def system_prompt(self) -> str:
        return "dummy"

    def execute(self, **kwargs):
        return {}


def _cfg(**overrides) -> Config:
    """构建测试用 Config。"""
    base = Config(
        provider="default_provider",
        model="default-model",
        providers={
            "default_provider": ProviderConfig(api_key="sk-default", base_url="https://api.default.com/v1"),
            "pro_provider": ProviderConfig(api_key="sk-pro", base_url="https://api.pro.com/v1"),
        },
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def _make_agent(cfg: Config, name: str = "test_role") -> _DummyAgent:
    """创建测试 Agent 实例。"""
    return _DummyAgent(
        cfg=cfg,
        runner=None,
        store=None,
        assets=None,
        emit_event=lambda e: None,
        emit_stream=lambda ch, d: None,
    )


# === 无角色配置 → 回退全局默认 ===

def test_fallback_to_global_default():
    """无 roles 配置时，使用全局 provider + model。"""
    cfg = _cfg()
    agent = _make_agent(cfg)
    client = agent.build_client()
    assert client.api_key == "sk-default"
    assert client.model == "default-model"
    assert client.base_url == "https://api.default.com/v1"


# === 有角色配置 → 使用角色专属 ===

def test_role_specific_provider_and_model():
    """有 roles[name] 配置时，使用角色专属 provider + model。"""
    cfg = _cfg(roles={
        "test_role": RoleConfig(provider="pro_provider", model="deepseek-reasoner"),
    })
    agent = _make_agent(cfg)
    client = agent.build_client()
    assert client.api_key == "sk-pro"
    assert client.model == "deepseek-reasoner"
    assert client.base_url == "https://api.pro.com/v1"


# === 角色配置不完整 → 回退全局 ===

def test_role_config_missing_provider():
    """roles[name] 存在但 provider 为空 → 回退全局。"""
    cfg = _cfg(roles={
        "test_role": RoleConfig(provider="", model="some-model"),
    })
    agent = _make_agent(cfg)
    client = agent.build_client()
    assert client.api_key == "sk-default"
    assert client.model == "default-model"


def test_role_config_missing_model():
    """roles[name] 存在但 model 为空 → 回退全局。"""
    cfg = _cfg(roles={
        "test_role": RoleConfig(provider="pro_provider", model=""),
    })
    agent = _make_agent(cfg)
    client = agent.build_client()
    assert client.api_key == "sk-default"
    assert client.model == "default-model"


# === 角色配置的 provider 不存在 → 报错 ===

def test_role_provider_not_exist():
    """roles[name] 引用了不存在的 provider → RuntimeError。"""
    cfg = _cfg(roles={
        "test_role": RoleConfig(provider="nonexistent", model="some-model"),
    })
    agent = _make_agent(cfg)
    with pytest.raises(RuntimeError, match="nonexistent.*api_key 未配置"):
        agent.build_client()


# === 角色配置的 api_key 为占位值 → 报错 ===

def test_role_provider_placeholder_key():
    """roles[name] 的 provider api_key 为占位值 → RuntimeError。"""
    cfg = _cfg()
    cfg.providers["pro_provider"] = ProviderConfig(api_key="dummy-key", base_url="https://api.pro.com/v1")
    cfg.roles["test_role"] = RoleConfig(provider="pro_provider", model="some-model")
    agent = _make_agent(cfg)
    with pytest.raises(RuntimeError, match="pro_provider.*api_key 为占位值"):
        agent.build_client()


# === 不同角色名使用不同配置 ===

def test_different_roles_different_configs():
    """不同角色名各自查找对应的 roles 配置。"""
    cfg = _cfg(roles={
        "architect": RoleConfig(provider="pro_provider", model="deepseek-reasoner"),
    })

    architect = _DummyAgent(cfg=cfg, runner=None, store=None, assets=None,
                            emit_event=lambda e: None, emit_stream=lambda ch, d: None)
    architect.name = "architect"
    client = architect.build_client()
    assert client.model == "deepseek-reasoner"

    writer = _DummyAgent(cfg=cfg, runner=None, store=None, assets=None,
                         emit_event=lambda e: None, emit_stream=lambda ch, d: None)
    writer.name = "writer"
    client = writer.build_client()
    assert client.model == "default-model"


# === 全局默认 api_key 为占位值 ===

def test_global_placeholder_key():
    """全局 provider api_key 为占位值 → RuntimeError。"""
    cfg = _cfg()
    cfg.providers["default_provider"] = ProviderConfig(api_key="dummy", base_url="")
    agent = _make_agent(cfg)
    with pytest.raises(RuntimeError, match="default_provider.*api_key 为占位值"):
        agent.build_client()


# === 全局 provider 不存在 ===

def test_global_provider_not_exist():
    """全局 provider 在 providers 中不存在 → RuntimeError。"""
    cfg = _cfg(provider="nonexistent")
    agent = _make_agent(cfg)
    with pytest.raises(RuntimeError, match="nonexistent.*api_key 未配置"):
        agent.build_client()


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
    print(f"test_per_role_llm: ok ({len(tests)} tests passed)")
