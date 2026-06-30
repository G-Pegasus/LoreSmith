"""
pytest 配置文件

提供测试fixtures、共享配置和测试工具函数。
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from ainovel_py.bootstrap.config import Config, ProviderConfig
from ainovel_py.internal_api.app import create_app
from ainovel_py.store.store import Store


@pytest.fixture
def temp_output_dir() -> Generator[Path, None, None]:
    """创建临时输出目录，测试结束后自动清理"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def test_store(temp_output_dir: Path) -> Store:
    """创建测试用的Store实例"""
    store = Store(str(temp_output_dir))
    store.init()
    return store


@pytest.fixture
def test_config(temp_output_dir: Path) -> Config:
    """创建测试用的Config实例"""
    config = Config(
        output_dir=str(temp_output_dir),
        provider="openai",
        model="gpt-4o-mini",
        providers={"openai": ProviderConfig(api_key="test-key")},
        style="default",
        context_window=128000,
    )
    config.fill_defaults()
    return config


@pytest.fixture
def test_client() -> TestClient:
    """创建测试用的FastAPI客户端"""
    app = create_app()
    return TestClient(app)


@pytest.fixture
def mock_api_key() -> str:
    """测试用的API密钥"""
    return "test-api-key-for-testing"


@pytest.fixture
def sample_story_data() -> dict:
    """示例故事数据"""
    return {
        "story_id": "test_story",
        "title": "测试小说",
        "premise": "这是一个测试用的小说前提",
        "style": "default",
        "genre": "玄幻",
        "characters": [
            {
                "name": "主角",
                "role": "protagonist",
                "description": "一个普通的年轻人"
            }
        ]
    }


@pytest.fixture
def sample_run_request(sample_story_data: dict, temp_output_dir: Path) -> dict:
    """示例运行请求"""
    return {
        "run_id": "test_run",
        "story": sample_story_data,
        "execution": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "context_window": 128000
        },
        "input": {
            "mode": "start",
            "prompt": "写一个测试故事"
        },
        "storage": {
            "kind": "local",
            "base_path": str(temp_output_dir)
        }
    }


@pytest.fixture
def sample_chapter_content() -> str:
    """示例章节内容"""
    return """# 第1章 雨夜觉醒

夜幕降临，大雨倾盆。

主角站在窗前，望着外面的雨幕，心中涌起一股莫名的情绪。

"这个世界，似乎有些不同了。"他喃喃自语。

一道闪电划破夜空，照亮了他的脸庞。在那一瞬间，他的眼中闪过一丝异样的光芒。

觉醒，就在这个雨夜悄然发生。
"""


@pytest.fixture
def sample_outline() -> dict:
    """示例大纲数据"""
    return {
        "chapters": [
            {
                "chapter": 1,
                "title": "雨夜觉醒",
                "summary": "主角在雨夜觉醒，获得特殊能力",
                "key_events": ["觉醒", "发现能力"]
            },
            {
                "chapter": 2,
                "title": "初试能力",
                "summary": "主角开始探索自己的能力",
                "key_events": ["测试能力", "遇到第一个挑战"]
            }
        ]
    }