"""
LangGraph 工作流节点定义模块

本模块定义了小说创作工作流中的所有核心节点，包括：
1. 状态操作工具函数（辅助函数）
2. 核心业务节点（上下文加载、章节规划、草稿生成、章节提交等）
3. 路由函数（决定节点间的流转方向）

节点流转图：
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ load_runtime_   │────▶│ novel_context_  │────▶│ plan_chapter_   │
│   context       │     │   node          │     │   node          │
└─────────────────┘     └─────────────────┘     └────────┬────────┘
     ▲                                                         │
     │                                                         ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│ checkpoint_     │◀────│ commit_chapter_ │◀────│ generate_draft_ │
│   node          │     │   node          │     │   node          │
└────────┬────────┘     └────────┬────────┘     └─────────────────┘
         │                       │
         │                       ▼
         │              ┌─────────────────┐
         │              │    review_node  │
         │              └────────┬────────┘
         │                       │
         │                       ▼
         │              ┌─────────────────┐
         │              │   rewrite_node  │
         │              └────────┬────────┘
         │                       │
         └───────────────────────┘

路由决策：
- route_after_load: 从加载上下文后决定下一步
- route_after_plan: 从规划章节后决定下一步
- route_after_commit: 从提交章节后决定下一步
- route_after_checkpoint: 从检查点后决定下一步
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

from ainovel_py.agents.hints import HintAction
from ainovel_py.agents.longform import generate_longform_outline_payload
from ainovel_py.agents.post_commit import plan_post_commit, plan_review_followup
from ainovel_py.agents.review_flow import save_arc_summary_followup, save_volume_summary_followup
from ainovel_py.agents.runner import (
    _extract_commit_metadata,
    _generate_review_payload,
    _run_write_commit_cycle,
)

from ..actions import plan_actions
from ainovel_py.domain.runtime import FlowState
from ainovel_py.domain.writing import PendingRunCheckpoint
from ainovel_py.host.events import Event

from ..state import GraphState

if TYPE_CHECKING:
    from ..core import LangGraphRuntime


# 最大执行步数限制（防止无限循环）
MAX_STEPS = 12


def _append_line(state: GraphState, line: str) -> None:
    """
    在状态中追加输出行
    
    Args:
        state: 图状态字典
        line: 要追加的行内容
    """
    lines = list(state.get("out_lines") or [])
    lines.append(line)
    state["out_lines"] = lines


def _set_pending_actions(state: GraphState, actions: list[str]) -> None:
    """
    设置待执行的动作列表
    
    Args:
        state: 图状态字典
        actions: 动作列表
    """
    state["pending_actions"] = actions
    state["pending_action"] = actions[0] if actions else "checkpoint"


def _pop_pending_action(state: GraphState) -> None:
    """
    弹出并移除第一个待执行动作
    
    Args:
        state: 图状态字典
    """
    actions = list(state.get("pending_actions") or [])
    if actions:
        actions.pop(0)
    state["pending_actions"] = actions
    state["pending_action"] = actions[0] if actions else "checkpoint"


def _enqueue_hint_actions(state: GraphState, actions: list[HintAction]) -> str:
    """
    将提示动作加入队列
    
    Args:
        state: 图状态字典
        actions: 提示动作列表
    
    Returns:
        下一个要执行的动作
    """
    plan = plan_actions(actions)
    _set_pending_actions(state, list(plan.queue))
    if plan.queue:
        _append_line(state, "[hint-actions] " + ", ".join(plan.queue))
    return plan.next_action


def load_runtime_context(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """
    【入口节点】加载运行时上下文
    
    工作流的起始节点，负责：
    1. 加载当前创作进度和各种状态
    2. 处理多种恢复场景：
       - 待确认检查点（用户暂停后等待确认）
       - 待提交章节（崩溃恢复）
       - 进行中章节（断点恢复）
       - 重写队列（进入重写模式）
    3. 根据状态决定下一步执行的动作
    
    Args:
        runtime: LangGraph 运行时实例
    
    Returns:
        节点函数
        
    输出状态字段：
        current_chapter: 当前要处理的章节号
        progress_snapshot: 进度快照（phase, flow, total_chapters等）
        rewrite_mode: 重写模式（rewrite/polish/空）
        pending_action: 下一步要执行的动作
    """
    def _node(state: GraphState) -> GraphState:
        progress = runtime.store.progress.load()
        pending = runtime.store.signals.load_pending_commit()
        pending_checkpoint = runtime.store.signals.load_pending_checkpoint()
        latest = runtime.store.checkpoints.latest_global()
        current_chapter = progress.next_chapter() if progress else 1
        next_action = "novel_context"
        rewrite_mode = ""
        seed_text = str(state.get("seed_text") or "").strip()
        
        # 处理重写/打磨模式
        if progress and progress.flow in {FlowState.REWRITING, FlowState.POLISHING} and progress.pending_rewrites:
            current_chapter = progress.pending_rewrites[0]
            rewrite_mode = "polish" if progress.flow == FlowState.POLISHING else "rewrite"
        
        # 处理待确认检查点
        if pending_checkpoint is not None:
            current_chapter = pending_checkpoint.next_chapter
            if seed_text == "__RUN_CONTINUE__":
                runtime.store.signals.clear_pending_checkpoint()
                next_action = "novel_context"
                _append_line(state, f"[run] confirmation accepted -> next_chapter={pending_checkpoint.next_chapter}")
            else:
                next_action = "finish"
                _append_line(state, f"[resume] awaiting_confirmation -> pause_after={pending_checkpoint.pause_after_chapter}")
        # 处理恢复模式
        elif state.get("resume_mode"):
              # 情况1：有待提交的章节 → 直接跳转到提交
            if pending is not None:
                current_chapter = pending.chapter
                next_action = "commit_chapter"
                #输出日志行
                _append_line(state, f"[resume] pending_commit -> chapter={pending.chapter} stage={pending.stage}")
            elif progress and progress.in_progress_chapter > 0:
                # 情况2：有进行中的章节 → 根据检查点决定下一步
                current_chapter = progress.in_progress_chapter
                step = latest.step if latest and latest.scope.kind == "chapter" and latest.scope.chapter == current_chapter else ""
                if step == "consistency_check":
                    next_action = "commit_chapter"
                elif step == "draft":
                    next_action = "commit_chapter"
                elif step == "plan":
                    # 检查查是否有本地草稿，有则跳转到提交，否则生成草稿
                    draft_content = runtime.store.drafts.load_draft(current_chapter)
                    if draft_content:
                        next_action = "commit_chapter"
                        _append_line(state, f"[resume] found_local_draft -> chapter={current_chapter} skip_generate")
                    else:
                        next_action = "generate_draft"
                else:
                    next_action = "novel_context"
                _append_line(state, f"[resume] in_progress -> chapter={current_chapter} step={step or 'unknown'}")
            elif progress and progress.pending_rewrites:
                current_chapter = progress.pending_rewrites[0]
                next_action = rewrite_mode or "rewrite"
                _append_line(state, f"[resume] rewrite_queue -> chapter={current_chapter} mode={rewrite_mode or 'rewrite'}")
        
        # 更新状态
        state["current_chapter"] = current_chapter
        state["progress_snapshot"] = {
            "phase": progress.phase if progress else "",
            "flow": progress.flow if progress else "",
            "total_chapters": progress.total_chapters if progress else 0,
            "completed_chapters": list(progress.completed_chapters) if progress else [],
            "pending_rewrites": list(progress.pending_rewrites) if progress else [],
            "rewrite_reason": progress.rewrite_reason if progress else "",
            "in_progress_chapter": progress.in_progress_chapter if progress else 0,
        }
        state["pending_review_for"] = None
        state["rewrite_mode"] = rewrite_mode
        state["pending_actions"] = []
        state["pending_action"] = next_action
        return state

    return _node


def novel_context_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """
    【上下文节点】获取章节上下文
    
    获取当前章节的写作上下文信息，包括：
    - 小说全局设定（世界观、人物、情节等）
    - 前序章节内容摘要
    - 重写模式下包含评审意见
    
    Args:
        runtime: LangGraph 运行时实例
    
    Returns:
        节点函数
        
    输入状态字段：
        current_chapter: 当前章节号
        
    输出状态字段：
        context: 章节上下文字典
    """
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("current_chapter") or 1)
        progress = runtime.store.progress.load()
        # 调用 novel_context 工具获取上下文
        context = runtime.runner.call_tool("novel_context", {"chapter": chapter})
        # 重写模式下构建重写专用上下文（包含评审意见）
        if progress and progress.flow in {FlowState.REWRITING, FlowState.POLISHING} and progress.pending_rewrites:
            context = runtime._build_rewrite_context(progress, context)
        state["context"] = context
        return state

    return _node


def plan_chapter_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """
    【规划节点】规划章节内容
    
    调用 plan_chapter 工具为当前章节生成详细写作计划，包括：
    - 章节主题和目标
    - 场景安排
    - 人物行动
    - 章节契约（风格、字数等要求）
    
    Args:
        runtime: LangGraph 运行时实例
    
    Returns:
        节点函数
        
    输入状态字段：
        current_chapter: 当前章节号
        context: 章节上下文
        seed_text: 用户创作指令
        
    输出状态字段：
        latest_plan: 章节规划结果
        pending_action: 下一步动作（固定为 generate_draft）
    """
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("current_chapter") or 1)
        context = state.get("context") or {}
        seed_text = str(state.get("seed_text") or "")
        progress = runtime.store.progress.load()
        # 构建日志摘要
        if progress and progress.flow in {FlowState.REWRITING, FlowState.POLISHING} and progress.pending_rewrites:
            summary = f"调用 plan_chapter (rewrite ch{chapter})"
        else:
            summary = f"调用 plan_chapter (ch{chapter})"
        # 发送工具调用事件
        runtime.emit_event(Event(time=datetime.now(), category="TOOL", summary=summary, level="info"))
        # 构建动态规划参数并调用工具
        plan_payload = runtime._build_dynamic_plan(seed_text, chapter, context)
        plan_res = runtime.runner.call_tool("plan_chapter", plan_payload)
        # 提取规划结果（失败时使用原始参数）
        latest_plan = plan_res.get("plan") or plan_payload
        state["latest_plan"] = latest_plan
        # 下一步固定为生成草稿
        state["pending_action"] = "generate_draft"
        return state

    return _node


def generate_draft_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """
    【生成节点】生成章节草稿
    
    调用 LLM 根据规划和上下文生成章节内容，是创作流程的核心计算节点。
    
    Args:
        runtime: LangGraph 运行时实例
    
    Returns:
        节点函数
        
    输入状态字段：
        current_chapter: 当前章节号
        context: 章节上下文
        latest_plan: 章节规划
        seed_text: 用户创作指令
        
    输出状态字段：
        latest_draft: 生成的章节草稿内容
        out_lines: 追加生成日志
    """
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("current_chapter") or 1)
        # 构建 LLM 客户端
        client = runtime.build_client()
        context = state.get("context") or {}
        plan = state.get("latest_plan") or {}
        contract = (plan.get("contract") or {}) if isinstance(plan, dict) else {}
        # 调用核心方法生成章节草稿
        draft, word_count = runtime._generate_chapter_with_context(
            client=client,
            seed_text=str(state.get("seed_text") or ""),
            chapter=chapter,
            context=context,
            plan=plan,
            contract=contract,
        )
        state["latest_draft"] = draft
        # 记录生成日志
        _append_line(state, f"[tool] draft_generation -> word_count={word_count}")
        return state

    return _node


def commit_chapter_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """
    【提交节点】提交章节
    
    完成章节的最终提交流程，包括：
    1. 提取章节元数据（标签、关键词等）
    2. 生成章节摘要
    3. 执行写作-提交循环（保存草稿、一致性检查、正式提交）
    4. 规划提交后动作（评审、重写、摘要等）
    
    Args:
        runtime: LangGraph 运行时实例
    
    Returns:
        节点函数
        
    输入状态字段：
        current_chapter: 当前章节号
        latest_draft: 章节草稿内容
        
    输出状态字段：
        latest_commit_result: 提交结果
        pending_review_for: 待评审章节号（可选）
        pending_action: 下一步动作
    """
    def _node(state: GraphState) -> GraphState:
        client = runtime.build_client()
        chapter = int(state.get("current_chapter") or 1)
        draft = str(state.get("latest_draft") or "")
        # 尝试从状态或存储加载草稿
        if not draft:
            draft = runtime.store.drafts.load_draft(chapter)
        if not draft:
            raise RuntimeError(f"chapter {chapter} draft is empty")
        # 提取元数据并生成摘要
        metadata = _extract_commit_metadata(client, chapter, draft)
        summary = str(metadata.get("summary", "") or runtime._summarize_chapter(client, chapter, draft))
        # 执行写作-提交循环
        draft_res, commit_res = _run_write_commit_cycle(runtime.runner, runtime.emit_event, chapter, draft, summary, metadata)
        state["latest_commit_result"] = commit_res
        # 记录提交日志
        _append_line(state, f"[tool] plan_chapter -> chapter={chapter}")
        _append_line(state, f"[tool] draft_chapter -> word_count={draft_res.get('word_count', 0)}")
        _append_line(state, f"[tool] commit_chapter -> next={commit_res.get('next_chapter', chapter + 1)}")
        # 规划提交后动作
        plan = plan_post_commit(commit_res, chapter)
        if plan.hints:
            _append_line(state, "[hints] " + " | ".join(plan.hints))
        # 入队提示动作并确定下一步
        next_action = _enqueue_hint_actions(state, plan.actions)
        state["pending_review_for"] = plan.pending_review_for
        state["pending_action"] = next_action if plan.next_action == next_action or next_action != "checkpoint" else plan.next_action
        return state

    return _node


def review_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """
    【评审节点】章节质量评审
    
    调用 save_review 工具对指定章节进行质量评审，包括：
    - 内容质量评估
    - 逻辑一致性检查
    - 建议改进方向
    
    Args:
        runtime: LangGraph 运行时实例
    
    Returns:
        节点函数
        
    输入状态字段：
        pending_review_for: 待评审章节号
        
    输出状态字段：
        latest_review_result: 评审结果
        pending_action: 下一步动作（可能是重写/打磨/继续）
    """
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("pending_review_for") or 0)
        # 验证章节号有效性
        if chapter <= 0:
            state["pending_action"] = "checkpoint"
            return state
        # 构建评审请求并调用工具
        client = runtime.build_client()
        review_payload = _generate_review_payload(client, runtime.runner, chapter)
        runtime.emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 save_review (ch{chapter})", level="info"))
        review_res = runtime.runner.call_tool("save_review", review_payload)
        state["latest_review_result"] = review_res
        # 记录评审日志
        _append_line(state, f"[tool] save_review -> final_verdict={review_res.get('final_verdict', '')}")
        # 规划评审后续动作
        plan = plan_review_followup(review_res)
        next_action = _enqueue_hint_actions(state, plan.actions) if plan.actions else plan.next_action
        state["pending_review_for"] = None
        state["pending_action"] = next_action
        return state

    return _node


def rewrite_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """
    【重写节点】进入重写模式
    
    设置重写模式并跳转到上下文获取节点，开始重写流程。
    
    Args:
        runtime: LangGraph 运行时实例
    
    Returns:
        节点函数
        
    输入状态字段：
        pending_action: 重写模式（rewrite/polish）
        rewrite_mode: 重写模式
        
    输出状态字段：
        current_chapter: 待重写章节号
        rewrite_mode: 重写模式
        pending_action: 下一步动作（固定为 novel_context）
    """
    def _node(state: GraphState) -> GraphState:
        progress = runtime.store.progress.load()
        chapter = int(state.get("current_chapter") or 1)
        # 获取重写模式
        rewrite_mode = str(state.get("pending_action") or state.get("rewrite_mode") or "rewrite")
        # 从待重写队列获取章节
        if progress and progress.pending_rewrites:
            chapter = progress.pending_rewrites[0]
        state["current_chapter"] = chapter
        state["rewrite_mode"] = rewrite_mode
        # 记录重写日志
        _append_line(state, f"[rewrite] mode={rewrite_mode} chapter={chapter}")
        # 下一步跳转到上下文获取
        state["pending_action"] = "novel_context"
        return state

    return _node


def arc_summary_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """
    【摘要节点】保存篇章摘要
    
    在完成一个篇章（Arc）后，保存该篇章的总结摘要，用于后续章节的上下文引用。
    
    Args:
        runtime: LangGraph 运行时实例
    
    Returns:
        节点函数
        
    输入状态字段：
        current_chapter: 当前章节号
        out_lines: 输出日志列表
        
    输出状态字段：
        out_lines: 更新后的日志列表
        pending_action: 队列中的下一个动作
    """
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("current_chapter") or 1)
        out_lines = list(state.get("out_lines") or [])
        # 保存篇章摘要
        save_arc_summary_followup(runtime.runner, runtime.emit_event, chapter, out_lines)
        state["out_lines"] = out_lines
        # 弹出队列中的下一个动作
        _pop_pending_action(state)
        return state

    return _node


def volume_summary_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """
    【摘要节点】保存卷摘要
    
    在完成一卷（Volume）后，保存该卷的总结摘要，用于后续卷的上下文引用。
    
    Args:
        runtime: LangGraph 运行时实例
    
    Returns:
        节点函数
        
    输入状态字段：
        current_chapter: 当前章节号
        out_lines: 输出日志列表
        
    输出状态字段：
        out_lines: 更新后的日志列表
        pending_action: 队列中的下一个动作
    """
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("current_chapter") or 1)
        progress = runtime.store.progress.load()
        volume = max(1, progress.current_volume) if progress else 1
        out_lines = list(state.get("out_lines") or [])
        # 保存卷摘要
        save_volume_summary_followup(runtime.runner, runtime.emit_event, chapter, out_lines, volume=volume, always=True)
        state["out_lines"] = out_lines
        # 弹出队列中的下一个动作
        _pop_pending_action(state)
        return state

    return _node


def expand_arc_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """
    【扩展节点】扩展篇章或添加新卷
    
    当当前卷的所有篇章完成后，扩展大纲：
    - 如果当前卷有下一篇章，扩展该篇章的内容
    - 如果当前卷已完成，添加新卷
    
    Args:
        runtime: LangGraph 运行时实例
    
    Returns:
        节点函数
        
    输入状态字段：
        current_chapter: 当前章节号
        
    输出状态字段：
        out_lines: 更新后的日志列表
        pending_action: 队列中的下一个动作
    """
    def _node(state: GraphState) -> GraphState:
        chapter = int(state.get("current_chapter") or 1)
        client = runtime.build_client()
        progress = runtime.store.progress.load()
        planning_tier = runtime._effective_planning_tier()
        if progress and progress.layered:
            # 分层大纲模式：检查是否有下一篇章
            volumes = runtime.store.outline.load_layered_outline()
            current_volume = max(1, progress.current_volume or 1)
            current_arc = max(1, progress.current_arc or 1)
            target_arc = current_arc + 1
            has_target_arc = False
            for vol in volumes:
                if vol.index == current_volume:
                    has_target_arc = any(arc.index == target_arc for arc in vol.arcs)
                    break
            if has_target_arc:
                # 扩展下一篇章
                payload = generate_longform_outline_payload(client, runtime.assets, planning_tier, chapter, "expand_arc")
                runtime.emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 save_foundation expand_arc (ch{chapter})", level="info"))
                runtime.runner.call_tool(
                    "save_foundation",
                    {"type": "expand_arc", "volume": current_volume, "arc": target_arc, "content": payload.get("chapters", [])},
                )
                _append_line(state, "[tool] save_foundation -> expand_arc")
            else:
                # 添加新卷
                payload = generate_longform_outline_payload(client, runtime.assets, planning_tier, chapter, "append_volume")
                runtime.emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 save_foundation append_volume (ch{chapter})", level="info"))
                runtime.runner.call_tool("save_foundation", {"type": "append_volume", "content": payload})
                _append_line(state, "[tool] save_foundation -> append_volume")
        else:
            # 非分层模式：直接添加新卷
            payload = generate_longform_outline_payload(client, runtime.assets, planning_tier, chapter, "append_volume")
            runtime.emit_event(Event(time=datetime.now(), category="TOOL", summary=f"调用 save_foundation append_volume (ch{chapter})", level="info"))
            runtime.runner.call_tool("save_foundation", {"type": "append_volume", "content": payload})
            _append_line(state, "[tool] save_foundation -> append_volume")
        # 弹出队列中的下一个动作
        _pop_pending_action(state)
        return state

    return _node


def checkpoint_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """
    【检查点节点】进度检查与控制
    
    核心控制节点，负责：
    1. 检查待执行动作队列
    2. 判断是否完成所有章节
    3. 判断是否达到最大步数限制
    4. 实现五章暂停机制（每5章暂停等待用户确认）
    5. 决定是否继续或结束流程
    
    Args:
        runtime: LangGraph 运行时实例
    
    Returns:
        节点函数
        
    输入状态字段：
        current_chapter: 当前章节号
        pending_actions: 待执行动作队列
        
    输出状态字段：
        current_chapter: 下一章节号
        pending_action: 下一步动作（continue/finish/其他动作）
    """
    def _node(state: GraphState) -> GraphState:
        progress = runtime.store.progress.load()
        chapter = int(state.get("current_chapter") or 1)
        completed = list(progress.completed_chapters) if progress else []
        total = progress.total_chapters if progress else 0
        steps = len(completed)
        pending_actions = list(state.get("pending_actions") or [])
        
        # 1. 如果有待执行动作，优先执行
        if pending_actions:
            state["pending_action"] = pending_actions[0]
            return state
        
        # 2. 如果已完成所有章节，结束流程
        if progress and total > 0 and chapter >= total and chapter in completed:
            state["pending_action"] = "finish"
            return state
        
        # 3. 如果达到最大步数或被中止，结束流程
        if steps >= MAX_STEPS or runtime._aborted:
            state["pending_action"] = "finish"
            return state
        
        # 4. 五章暂停机制：每完成5章暂停等待用户确认
        next_chapter = progress.next_chapter() if progress else chapter + 1
        if steps > 0 and steps % 5 == 0:
            pending = PendingRunCheckpoint(
                pause_after_chapter=max(completed) if completed else chapter,
                next_chapter=next_chapter,
                completed_count=steps,
            )
            # 保存暂停状态并通知前端
            runtime.store.signals.save_pending_checkpoint(pending)
            runtime.emit_checkpoint_pending(pending)
            state["current_chapter"] = next_chapter
            state["pending_action"] = "finish"
            return state
        
        # 5. 继续下一章节
        state["current_chapter"] = next_chapter
        state["pending_action"] = "continue"
        return state

    return _node


def finish_node(runtime: "LangGraphRuntime") -> Callable[[GraphState], GraphState]:
    """
    【结束节点】结束流程
    
    标记流程结束，设置 pending_action 为 finish。
    
    Args:
        runtime: LangGraph 运行时实例
    
    Returns:
        节点函数
    """
    def _node(state: GraphState) -> GraphState:
        state["pending_action"] = "finish"
        return state

    return _node


# ============ 路由函数 ============

def route_after_load(state: GraphState) -> str:
    """
    路由：加载上下文后决定下一步
    
    根据 load_runtime_context 节点设置的 pending_action 决定流向：
    - generate_draft: 直接生成草稿（恢复模式）
    - commit_chapter: 直接提交章节（恢复模式）
    - rewrite/polish: 进入重写模式
    - finish: 结束流程
    - 默认: 获取章节上下文
    
    Args:
        state: 图状态
        
    Returns:
        目标节点名称
    """
    action = str(state.get("pending_action") or "novel_context")
    if action == "generate_draft":
        return "generate_draft"
    if action == "commit_chapter":
        return "commit_chapter"
    if action in {"rewrite", "polish"}:
        return "rewrite"
    if action == "finish":
        return "finish"
    return "novel_context"


def route_after_plan(state: GraphState) -> str:
    """
    路由：规划章节后决定下一步
    
    规划完成后通常流向生成草稿，除非需要结束。
    
    Args:
        state: 图状态
        
    Returns:
        目标节点名称
    """
    action = str(state.get("pending_action") or "generate_draft")
    if action == "finish":
        return "finish"
    return "generate_draft"


def route_after_commit(state: GraphState) -> str:
    """
    路由：提交章节后决定下一步
    
    根据提交结果决定后续动作：
    - review: 评审章节
    - rewrite/polish: 进入重写模式
    - arc_summary: 保存篇章摘要
    - volume_summary: 保存卷摘要
    - expand_arc: 扩展篇章
    - finish: 结束流程
    - 默认: 检查点
    
    Args:
        state: 图状态
        
    Returns:
        目标节点名称
    """
    action = str(state.get("pending_action") or "checkpoint")
    if action == "review":
        return "review"
    if action in {"rewrite", "polish"}:
        return "rewrite"
    if action == "arc_summary":
        return "arc_summary"
    if action == "volume_summary":
        return "volume_summary"
    if action == "expand_arc":
        return "expand_arc"
    if action == "finish":
        return "finish"
    return "checkpoint"


def route_after_checkpoint(state: GraphState) -> str:
    """
    路由：检查点后决定下一步
    
    根据检查点判断结果决定后续动作：
    - novel_context/continue: 继续下一章
    - rewrite/polish: 进入重写模式
    - arc_summary: 保存篇章摘要
    - volume_summary: 保存卷摘要
    - expand_arc: 扩展篇章
    - 默认: 结束流程
    
    Args:
        state: 图状态
        
    Returns:
        目标节点名称
    """
    action = str(state.get("pending_action") or "finish")
    if action == "novel_context" or action == "continue":
        return "novel_context"
    if action in {"rewrite", "polish"}:
        return "rewrite"
    if action == "arc_summary":
        return "arc_summary"
    if action == "volume_summary":
        return "volume_summary"
    if action == "expand_arc":
        return "expand_arc"
    return "finish"
