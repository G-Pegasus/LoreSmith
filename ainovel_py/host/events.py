from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class StreamChunk:
    """
    流式输出块
    
    用于实时传输 LLM 生成的内容片段，支持 content 和 thinking 两种通道。
    """
    channel: str = "content"  # 通道类型（content/thinking）
    delta: str = ""           # 内容片段


@dataclass
class Event:
    """
    事件对象
    
    用于记录系统运行过程中的各种事件，支持不同分类和级别。
    """
    time: datetime = field(default_factory=datetime.now)  # 事件时间
    category: str = "SYSTEM"                             # 事件分类
    summary: str = ""                                    # 事件摘要
    level: str = "info"                                  # 事件级别（info/warn/error/success）


def build_start_prompt(prompt: str) -> str:
    """构建启动提示词，包装用户输入"""
    text = prompt.strip()
    return (
        "请根据以下创作要求开始创作一部小说。进入规划后，Premise 第一行必须输出 `# 书名`。"
        "章节数量由你根据故事需要自行决定。\n\n[创作要求]\n"
        + text
        + "\n\n若某些细节未明确，请在不违背用户方向的前提下自行补全。"
    )


@dataclass
class UISnapshot:
    """
    UI 快照
    
    用于向前端展示当前创作状态的快照，包含进度、上下文、人物等信息。
    """
    provider: str = ""                        # 服务提供商
    model_name: str = ""                      # 模型名称
    style: str = ""                           # 写作风格
    runtime_state: str = ""                   # 运行时状态
    status_label: str = ""                    # 状态标签
    phase: str = ""                           # 当前阶段
    flow: str = ""                            # 当前流程
    current_chapter: int = 0                  # 当前章节
    total_chapters: int = 0                   # 总章节数
    completed_count: int = 0                  # 已完成章节数
    total_word_count: int = 0                 # 总字数
    pending_rewrites: list[int] = field(default_factory=list)  # 待重写章节
    rewrite_reason: str = ""                  # 重写原因
    pending_steer: str = ""                   # 待处理干预指令
    premise: str = ""                         # 故事前提
    outline: list[dict[str, Any]] = field(default_factory=list)  # 大纲预览
    characters: list[str] = field(default_factory=list)          # 人物列表
    recent_summaries: list[str] = field(default_factory=list)    # 最近摘要
    last_review_summary: str = ""             # 最后评审摘要
    backend: str = ""                         # 后端类型
    context_window: int = 0                   # 上下文窗口大小
    context_tokens: int = 0                   # 当前上下文 token 数
    context_percent: float = 0.0              # 上下文使用百分比
    agent_status: list[str] = field(default_factory=list)        # Agent 状态列表


def replay_stream_chunk(payload: object) -> StreamChunk | None:
    if not isinstance(payload, dict):
        return None
    delta = payload.get("delta")
    if not isinstance(delta, str) or not delta:
        return None
    channel = str(payload.get("channel", "content") or "content").strip().lower()
    if channel not in {"content", "thinking"}:
        channel = "content"
    return StreamChunk(channel=channel, delta=delta)


def replay_delta_text(payload: object) -> str:
    chunk = replay_stream_chunk(payload)
    if chunk is None:
        return ""
    return chunk.delta
