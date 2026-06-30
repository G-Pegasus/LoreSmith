"""
Agent 测试脚本

用于测试 Agent 工作流程的完整性和正确性。
支持多种测试场景：单章节生成、多章节生成、恢复测试等。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ainovel_py.agents.build import build_coordinator_loop, build_tool_registry
from ainovel_py.bootstrap.config import Config, ProviderConfig
from ainovel_py.host.host import Host
from ainovel_py.store.store import Store


def create_test_config(output_dir: str, provider: str = "openai", model: str = "gpt-4o-mini") -> Config:
    """创建测试配置"""
    config = Config(
        output_dir=output_dir,
        provider=provider,
        model=model,
        providers={provider: ProviderConfig(api_key="test-key")},
        style="default",
        context_window=128000,
    )
    config.fill_defaults()
    return config


def test_single_chapter(output_dir: str) -> int:
    """测试单章节生成流程"""
    print("=" * 80)
    print("测试场景：单章节生成")
    print("=" * 80)
    
    store = Store(output_dir)
    store.init()
    
    config = create_test_config(output_dir)
    
    # 初始化基础数据
    store.story_data.premise.save("测试小说前提：一个年轻人在雨夜觉醒，获得特殊能力。")
    store.story_data.outline.save({
        "chapters": [
            {
                "chapter": 1,
                "title": "雨夜觉醒",
                "summary": "主角在雨夜觉醒",
                "key_events": ["觉醒"]
            }
        ]
    })
    
    # 创建 Host
    host = Host(config, store)
    
    # 启动运行
    print("\n启动 Agent 运行...")
    events = []
    for event in host.run("写第一章"):
        events.append(event)
        print(f"事件: {event['type']}")
    
    # 检查结果
    print("\n检查生成结果...")
    chapter = store.drafts.load_draft(1)
    if chapter:
        print(f"✓ 章节内容已生成，长度: {len(chapter)} 字符")
        print(f"前100字符: {chapter[:100]}...")
    else:
        print("✗ 章节内容未生成")
        return 1
    
    # 检查提交
    committed = store.story_data.chapters.load_chapter(1)
    if committed:
        print(f"✓ 章节已提交")
    else:
        print("✗ 章节未提交")
        return 1
    
    print("\n✓ 单章节生成测试通过")
    return 0


def test_multi_chapters(output_dir: str, num_chapters: int = 3) -> int:
    """测试多章节生成流程"""
    print("=" * 80)
    print(f"测试场景：多章节生成（{num_chapters}章）")
    print("=" * 80)
    
    store = Store(output_dir)
    store.init()
    
    config = create_test_config(output_dir)
    
    # 初始化基础数据
    store.story_data.premise.save("测试小说前提：一个年轻人在雨夜觉醒，获得特殊能力，开始探索这个世界。")
    
    outline = {
        "chapters": []
    }
    for i in range(1, num_chapters + 1):
        outline["chapters"].append({
            "chapter": i,
            "title": f"第{i}章",
            "summary": f"第{i}章内容",
            "key_events": [f"事件{i}"]
        })
    store.story_data.outline.save(outline)
    
    # 创建 Host
    host = Host(config, store)
    
    # 启动运行
    print(f"\n启动 Agent 运行，生成 {num_chapters} 章...")
    events = []
    for event in host.run(f"写前{num_chapters}章"):
        events.append(event)
        print(f"事件: {event['type']}")
    
    # 检查结果
    print("\n检查生成结果...")
    success_count = 0
    for i in range(1, num_chapters + 1):
        chapter = store.story_data.chapters.load_chapter(i)
        if chapter:
            print(f"✓ 第{i}章已生成并提交，长度: {len(chapter)} 字符")
            success_count += 1
        else:
            print(f"✗ 第{i}章未生成")
    
    if success_count == num_chapters:
        print(f"\n✓ 多章节生成测试通过（{success_count}/{num_chapters}）")
        return 0
    else:
        print(f"\n✗ 多章节生成测试失败（{success_count}/{num_chapters}）")
        return 1


def test_resume_flow(output_dir: str) -> int:
    """测试恢复流程"""
    print("=" * 80)
    print("测试场景：中断恢复")
    print("=" * 80)
    
    store = Store(output_dir)
    store.init()
    
    config = create_test_config(output_dir)
    
    # 初始化基础数据
    store.story_data.premise.save("测试小说前提：一个年轻人在雨夜觉醒。")
    store.story_data.outline.save({
        "chapters": [
            {"chapter": 1, "title": "雨夜觉醒", "summary": "主角觉醒", "key_events": ["觉醒"]},
            {"chapter": 2, "title": "初试能力", "summary": "主角测试能力", "key_events": ["测试"]}
        ]
    })
    
    # 第一次运行（生成第一章）
    print("\n第一次运行：生成第一章...")
    host1 = Host(config, store)
    events1 = []
    for event in host1.run("写第一章"):
        events1.append(event)
        print(f"事件: {event['type']}")
    
    # 检查第一章是否生成
    chapter1 = store.story_data.chapters.load_chapter(1)
    if not chapter1:
        print("✗ 第一章未生成，无法测试恢复")
        return 1
    
    print(f"✓ 第一章已生成，长度: {len(chapter1)} 字符")
    
    # 保存进度状态
    progress = store.progress.load()
    print(f"当前进度: 章节 {progress.current_chapter}, 状态 {progress.flow}")
    
    # 第二次运行（恢复并继续）
    print("\n第二次运行：从检查点恢复...")
    host2 = Host(config, store)
    events2 = []
    for event in host2.run("继续写第二章"):
        events2.append(event)
        print(f"事件: {event['type']}")
    
    # 检查第二章是否生成
    chapter2 = store.story_data.chapters.load_chapter(2)
    if chapter2:
        print(f"✓ 第二章已生成，长度: {len(chapter2)} 字符")
        print("\n✓ 恢复流程测试通过")
        return 0
    else:
        print("✗ 第二章未生成")
        print("\n✗ 恢复流程测试失败")
        return 1


def test_agent_components(output_dir: str) -> int:
    """测试各个 Agent 组件"""
    print("=" * 80)
    print("测试场景：Agent 组件测试")
    print("=" * 80)
    
    store = Store(output_dir)
    store.init()
    
    config = create_test_config(output_dir)
    
    # 测试工具注册
    print("\n测试工具注册...")
    tools = build_tool_registry(store)
    required_tools = [
        "novel_context",
        "plan_chapter",
        "draft_chapter",
        "commit_chapter",
        "read_chapter",
        "check_consistency",
    ]
    
    missing_tools = []
    for tool_name in required_tools:
        if tool_name not in tools:
            missing_tools.append(tool_name)
    
    if missing_tools:
        print(f"✗ 缺少工具: {missing_tools}")
        return 1
    else:
        print(f"✓ 所有必需工具已注册: {required_tools}")
    
    # 测试 CoordinatorLoop 构建
    print("\n测试 CoordinatorLoop 构建...")
    loop = build_coordinator_loop(config, store, lambda e: None, lambda c, d: None)
    if loop:
        print("✓ CoordinatorLoop 构建成功")
    else:
        print("✗ CoordinatorLoop 构建失败")
        return 1
    
    # 测试 LangGraph Runtime
    print("\n测试 LangGraph Runtime...")
    try:
        from ainovel_py.agents.orchestrator.langgraph.core import LangGraphRuntime
        if isinstance(loop.backend, LangGraphRuntime):
            print("✓ LangGraph Runtime 正确初始化")
        else:
            print("✗ LangGraph Runtime 未正确初始化")
            return 1
    except Exception as e:
        print(f"✗ LangGraph Runtime 加载失败: {e}")
        return 1
    
    print("\n✓ Agent 组件测试通过")
    return 0


def main() -> int:
    """主函数"""
    parser = argparse.ArgumentParser(description="LoreSmith Agent 测试脚本")
    parser.add_argument(
        "--test",
        choices=["single", "multi", "resume", "components", "all"],
        default="all",
        help="选择测试场景"
    )
    parser.add_argument(
        "--output",
        default="output/test_agent",
        help="测试输出目录"
    )
    parser.add_argument(
        "--chapters",
        type=int,
        default=3,
        help="多章节测试的章节数"
    )
    
    args = parser.parse_args()
    
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    results = {}
    
    if args.test in ("single", "all"):
        results["single"] = test_single_chapter(str(output_dir / "single"))
    
    if args.test in ("multi", "all"):
        results["multi"] = test_multi_chapters(str(output_dir / "multi"), args.chapters)
    
    if args.test in ("resume", "all"):
        results["resume"] = test_resume_flow(str(output_dir / "resume"))
    
    if args.test in ("components", "all"):
        results["components"] = test_agent_components(str(output_dir / "components"))
    
    # 输出总结
    print("\n" + "=" * 80)
    print("测试总结")
    print("=" * 80)
    
    for test_name, result in results.items():
        status = "✓ 通过" if result == 0 else "✗ 失败"
        print(f"{test_name}: {status}")
    
    failed_count = sum(1 for r in results.values() if r != 0)
    if failed_count == 0:
        print("\n✓ 所有测试通过")
        return 0
    else:
        print(f"\n✗ {failed_count} 个测试失败")
        return 1


if __name__ == "__main__":
    sys.exit(main())