"""
快速测试脚本

用于快速验证 Agent 的基本功能是否正常工作。
不依赖外部 API，使用模拟数据进行测试。
"""
from __future__ import annotations

import sys
from pathlib import Path


def test_imports() -> bool:
    """测试所有关键模块是否能正常导入"""
    print("测试模块导入...")
    
    modules = [
        "ainovel_py.agents",
        "ainovel_py.agents.build",
        "ainovel_py.agents.runner",
        "ainovel_py.agents.orchestrator.langgraph.core",
        "ainovel_py.bootstrap.config",
        "ainovel_py.store.store",
        "ainovel_py.host.host",
        "ainovel_py.internal_api.app",
        "ainovel_py.tools",
    ]
    
    failed = []
    for module in modules:
        try:
            __import__(module)
            print(f"  ✓ {module}")
        except Exception as e:
            print(f"  ✗ {module}: {e}")
            failed.append(module)
    
    return len(failed) == 0


def test_config_creation() -> bool:
    """测试配置创建"""
    print("\n测试配置创建...")
    
    try:
        from ainovel_py.bootstrap.config import Config, ProviderConfig
        
        config = Config(
            output_dir="output/test",
            provider="openai",
            model="gpt-4o-mini",
            providers={"openai": ProviderConfig(api_key="test-key")},
            style="default",
            context_window=128000,
        )
        config.fill_defaults()
        
        print(f"  ✓ 配置创建成功")
        print(f"    Provider: {config.provider}")
        print(f"    Model: {config.model}")
        print(f"    Context Window: {config.context_window}")
        return True
    except Exception as e:
        print(f"  ✗ 配置创建失败: {e}")
        return False


def test_store_init() -> bool:
    """测试存储初始化"""
    print("\n测试存储初始化...")
    
    try:
        from ainovel_py.store.store import Store
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Store(tmpdir)
            store.init()
            
            print(f"  ✓ 存储初始化成功")
            print(f"    目录: {tmpdir}")
            
            # 测试各个存储模块
            modules = [
                "progress",
                "run_meta",
                "runtime",
                "outline",
                "characters",
                "drafts",
                "summaries",
                "world",
                "signals",
                "checkpoints",
            ]
            
            for module in modules:
                if hasattr(store, module):
                    print(f"    ✓ {module} 模块可用")
                else:
                    print(f"    ✗ {module} 模块缺失")
                    return False
            
            return True
    except Exception as e:
        print(f"  ✗ 存储初始化失败: {e}")
        return False


def test_tool_registry() -> bool:
    """测试工具注册"""
    print("\n测试工具注册...")
    
    try:
        from ainovel_py.agents.build import build_tool_registry
        from ainovel_py.store.store import Store
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Store(tmpdir)
            store.init()
            
            tools = build_tool_registry(store)
            
            required_tools = [
                "novel_context",
                "plan_chapter",
                "draft_chapter",
                "commit_chapter",
                "read_chapter",
                "check_consistency",
            ]
            
            print(f"  ✓ 工具注册成功")
            print(f"    已注册工具数: {len(tools)}")
            
            missing = []
            for tool in required_tools:
                if tool in tools:
                    print(f"    ✓ {tool}")
                else:
                    print(f"    ✗ {tool} 缺失")
                    missing.append(tool)
            
            return len(missing) == 0
    except Exception as e:
        print(f"  ✗ 工具注册失败: {e}")
        return False


def test_langgraph_runtime() -> bool:
    """测试 LangGraph Runtime"""
    print("\n测试 LangGraph Runtime...")
    
    try:
        from ainovel_py.agents.orchestrator.langgraph.core import LangGraphRuntime
        from ainovel_py.bootstrap.config import Config, ProviderConfig
        from ainovel_py.store.store import Store
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Store(tmpdir)
            store.init()
            
            config = Config(
                output_dir=tmpdir,
                provider="openai",
                model="gpt-4o-mini",
                providers={"openai": ProviderConfig(api_key="test-key")},
                style="default",
                context_window=128000,
            )
            config.fill_defaults()
            
            runtime = LangGraphRuntime(config, store)
            
            print(f"  ✓ LangGraph Runtime 创建成功")
            print(f"    Backend 类型: {type(runtime).__name__}")
            
            # 检查关键方法
            methods = ["run", "resume", "cancel"]
            for method in methods:
                if hasattr(runtime, method):
                    print(f"    ✓ {method} 方法可用")
                else:
                    print(f"    ✗ {method} 方法缺失")
                    return False
            
            return True
    except Exception as e:
        print(f"  ✗ LangGraph Runtime 测试失败: {e}")
        return False


def test_fastapi_app() -> bool:
    """测试 FastAPI 应用"""
    print("\n测试 FastAPI 应用...")
    
    try:
        from ainovel_py.internal_api.app import create_app
        
        app = create_app()
        
        print(f"  ✓ FastAPI 应用创建成功")
        print(f"    App 标题: {app.title}")
        print(f"    App 版本: {app.version}")
        
        # 检查路由
        routes = [route.path for route in app.routes]
        print(f"    已注册路由数: {len(routes)}")
        
        # 检查关键路由
        key_routes = [
            "/internal/v1/health",
            "/internal/v1/runs",
        ]
        
        missing_routes = []
        for route in key_routes:
            if route in routes:
                print(f"    ✓ {route}")
            else:
                print(f"    ✗ {route} 缺失")
                missing_routes.append(route)
        
        return len(missing_routes) == 0
    except Exception as e:
        print(f"  ✗ FastAPI 应用测试失败: {e}")
        return False


def main() -> int:
    """主函数"""
    print("=" * 80)
    print("LoreSmith 快速测试")
    print("=" * 80)
    
    tests = [
        ("模块导入", test_imports),
        ("配置创建", test_config_creation),
        ("存储初始化", test_store_init),
        ("工具注册", test_tool_registry),
        ("LangGraph Runtime", test_langgraph_runtime),
        ("FastAPI 应用", test_fastapi_app),
    ]
    
    results = {}
    for name, test_func in tests:
        try:
            results[name] = test_func()
        except Exception as e:
            print(f"\n测试 {name} 时发生异常: {e}")
            results[name] = False
    
    # 输出总结
    print("\n" + "=" * 80)
    print("测试总结")
    print("=" * 80)
    
    passed = sum(1 for r in results.values() if r)
    total = len(results)
    
    for name, result in results.items():
        status = "✓ 通过" if result else "✗ 失败"
        print(f"{name}: {status}")
    
    print(f"\n总计: {passed}/{total} 测试通过")
    
    if passed == total:
        print("\n✓ 所有测试通过，系统运行正常")
        return 0
    else:
        print(f"\n✗ {total - passed} 个测试失败，请检查系统配置")
        return 1


if __name__ == "__main__":
    sys.exit(main())