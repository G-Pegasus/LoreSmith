"""
主机控制器模块 (Host Controller)

Host 是 LoreSmith 小说创作系统的核心控制器，相当于"总指挥"角色。
它不直接执行具体的创作任务，而是负责协调各个子系统的工作。

核心职责：
1. 生命周期管理：控制系统在 idle/running/completed/paused 四种状态间转换
2. 子系统协调：初始化和连接配置、存储、协调器循环等组件
3. 事件队列管理：维护四个 asyncio.Queue 用于异步通信
4. 流程控制：提供 start/resume/continue/steer/abort 等操作接口
5. 检查点处理：支持暂停等待确认和断点恢复

设计模式：
- 门面模式 (Facade)：对外提供统一的高层 API，隐藏内部复杂性
- 观察者模式 (Observer)：通过队列和回调函数实现事件通知
- 状态模式 (State)：lifecycle 字段控制允许的操作

使用场景：
- 由 internal_api/service.py 的 RunService 创建和管理
- 由 internal_api/worker.py 的 WorkerManager 调用其 start/resume/abort 方法
- 其 report()/snapshot()/replay_queue() 方法被 API 层调用返回数据给前端

典型调用链路：
Java前端 → FastAPI routes → RunService → Host → CoordinatorLoop → LangGraph状态机 → LLM/Tools
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime

from ainovel_py.agents import OrchestratorBackend, build_coordinator_loop
from ainovel_py.agents.llm_client import OpenAICompatClient
from ainovel_py.agents.build import build_tool_registry
from ainovel_py.agents.runner import AgentRunner
from ainovel_py.bootstrap.config import Config
from ainovel_py.domain.runtime import Phase
from ainovel_py.domain.runtime_events import RuntimeQueueItem, RuntimeQueueKind, RuntimeQueuePriority
from ainovel_py.domain.writing import PendingRunCheckpoint
from ainovel_py.host.events import Event, StreamChunk, UISnapshot, build_start_prompt
from ainovel_py.host.resume import build_resume_prompt
from ainovel_py.store.store import Store


@dataclass
class _DummyAskUser:
    """
    用户询问占位对象
    
    用于处理需要用户确认的场景（如检查点确认）。
    提供 handler 设置接口，允许外部注册回调函数来处理用户交互。
    
    这是一个简单的占位实现，实际的用户交互逻辑在外部（Java 前端）处理。
    
    Attributes:
        handler: 用户询问的处理器回调函数
        
    Example:
        host.ask_user().set_handler(my_confirmation_handler)
    """
    handler: object = None

    def set_handler(self, handler: object) -> None:
        """
        设置用户询问处理器
        
        Args:
            handler: 处理用户确认/输入的回调函数
        """
        self.handler = handler


class Host:
    """
    主机控制器 (Host Controller)
    
    作为小说创作系统的核心控制器，负责整个创作流程的管理和协调。
    可以将其理解为一家"小说创作工作室"的店长——不亲自写作，
    但负责招聘团队、分配任务、监控进度、处理客户需求。
    
    主要职责详解：
    
    1️⃣ 生命周期管理 (Lifecycle Management)
       - idle: 空闲状态，可以接收新任务
       - running: 运行中，正在创作
       - completed: 创作完成（终态）
       - paused: 已暂停，可恢复
       
    2️⃣ 子系统协调 (Subsystem Coordination)
       - Config: 配置管理（模型选择、风格等）
       - Store: 数据持久化（文件存储）
       - CoordinatorLoop: 协调器循环（驱动 LangGraph 状态机）
       
    3️⃣ 事件队列系统 (Event Queue System)
       维护四个异步队列用于不同类型的通信：
       - events: 系统事件（工具调用、状态变化等）
       - stream_ch: 流式输出（LLM 生成的文本片段）
       - clear_ch: 清空信号（通知前端清空显示）
       - done_ch: 完成信号（通知运行结束）
       
    4️⃣ 流程控制接口 (Flow Control APIs)
       - start(prompt): 开始新的创作
       - resume(): 从断点恢复
       - continue_run(text): 追加内容或继续
       - steer(text): 用户干预指导
       - abort(): 中止当前运行
       
    5️⃣ 数据报告接口 (Reporting Interfaces)
       - report(): 返回结构化状态数据（供 API 使用）
       - snapshot(): 返回 UI 快照数据（供前端展示）
       - replay_queue(): 返回历史事件（供 SSE 推送）
       
    线程安全说明：
       - Host 本身不是线程安全的，但通过 asyncio.Queue 实现了线程间的安全通信
       - _safe_put() 方法提供了背压保护机制
       
    典型使用方式：
        # 创建 Host 实例
        cfg = Config(provider="deepseek", model="deepseek-chat")
        host = Host(cfg)
        
        # 开始创作
        host.start("写一本仙侠小说")
        
        # 查看进度
        status = host.report()
        print(f"已完成 {status['completed_chapters']} 章")
        
        # 暂停
        host.abort()
        
        # 恢复
        host.resume()
    """

    def __init__(self, cfg: Config) -> None:
        """
        初始化主机控制器
        
        这是整个系统的"开店"过程，会完成以下工作：
        
        步骤1: 配置准备
        - 调用 fill_defaults() 补全缺失的配置项（如默认输出目录、上下文窗口大小）
        - 调用 validate_base() 验证基础配置是否合法（API Key 是否存在等）
        
        步骤2: 存储系统初始化
        - 创建 Store 实例，指定输出目录
        - 调用 store.init() 创建必要的目录结构
        - 调用 store.run_meta.init() 初始化运行元数据文件
        
        步骤3: 协调器循环构建（核心！）
        - 调用 build_coordinator_loop() 构建完整的 Agent 系统
        - 内部会创建：AgentRunner（含11个工具）、LangGraphRuntime（状态机）
        - 将 emit_event 和 emit_stream 回调传入，实现事件外传
        
        步骤4: 通信队列创建
        - 创建四个 asyncio.Queue 用于异步通信
        - 设置合理的 maxsize 以防止内存溢出
        
        步骤5: 状态初始化
        - 设置 lifecycle 为 "idle"
        - 初始化其他内部状态变量
        
        Args:
            cfg: 系统配置对象，包含：
                - provider: LLM 服务商（openai/deepseek/qwen 等）
                - model: 模型名称
                - style: 写作风格
                - output_dir: 输出目录路径
                - context_window: 上下文窗口大小（token 数）
                - providers: 多服务商配置字典
                - roles: 角色级模型配置
                
        Raises:
            RuntimeError: 如果 API Key 未配置或是占位值
            
        Example:
            cfg = Config(
                provider="deepseek",
                model="deepseek-chat",
                output_dir="./output/novel",
                style="default",
                context_window=128000
            )
            host = Host(cfg)  # 完成全部初始化
        """
        cfg.fill_defaults()
        cfg.validate_base()
        self.cfg = cfg
        self.store = Store(cfg.output_dir)
        self.store.init()
        self.store.run_meta.init(cfg.style, cfg.provider, cfg.model)
        self.loop: OrchestratorBackend = build_coordinator_loop(
            self.cfg,
            self.store,
            emit_event=self._emit_event,
            emit_stream=self._emit_stream_chunk,
        )

        self.events: asyncio.Queue[Event] = asyncio.Queue(maxsize=100)
        self.stream_ch: asyncio.Queue[StreamChunk] = asyncio.Queue(maxsize=256)
        self.clear_ch: asyncio.Queue[bool] = asyncio.Queue(maxsize=4)
        self.done_ch: asyncio.Queue[bool] = asyncio.Queue(maxsize=4)

        self.lifecycle = "idle"
        self.idle_resume_count = 0
        self._closed = False
        self._ask_user = _DummyAskUser()

    def dir(self) -> str:
        """
        获取输出目录路径
        
        返回 Store 管理的输出目录绝对路径，
        用于外部获取文件位置信息。
        
        Returns:
            输出目录的绝对路径字符串
        """
        return self.store.dir()

    def report(self) -> dict[str, object]:
        """
        生成运行状态报告（结构化数据）
        
        此方法供 API 层（routes.py）调用，返回当前运行的详细状态。
        主要用于 Java 平台层的后端监控和数据展示。
        
        返回的数据包括：
        
        配置信息：
        - provider: 当前使用的 LLM 服务商
        - model: 当前使用的模型名称
        - style: 写作风格
        - output_dir: 输出目录路径
        
        进度信息：
        - lifecycle: 当前生命周期状态
        - completed_chapters: 已完成的章节数量
        - current_chapter: 当前进度的章节号
        - total_word_count: 总字数统计
        - flow: 当前处于的创作流程阶段
        - phase: 当前处于的创作阶段
        
        状态标记：
        - latest_checkpoint: 最新检查点信息（步骤、范围、序列号）
        - has_last_commit: 是否有最近一次提交记录
        - awaiting_confirmation: 是否正在等待用户确认（检查点暂停）
        
        Returns:
            包含所有状态信息的字典
            
        Note:
            如果 pending_checkpoint 存在，current_chapter 会显示为 next_chapter
            （即下一章要写的章节），而非当前已完成的章节
        """
        progress = self.store.progress.load()
        latest_cp = self.store.checkpoints.latest_global()
        last_commit = self.store.signals.load_last_commit()
        pending_checkpoint = self.store.signals.load_pending_checkpoint()
        current_chapter = progress.current_chapter if progress else 0
        if pending_checkpoint is not None:
            current_chapter = pending_checkpoint.next_chapter
        return {
            "provider": self.cfg.provider,
            "model": self.cfg.model,
            "style": self.cfg.style,
            "lifecycle": self.lifecycle,
            "output_dir": self.store.dir(),
            "completed_chapters": len(progress.completed_chapters) if progress else 0,
            "current_chapter": current_chapter,
            "total_word_count": progress.total_word_count if progress else 0,
            "flow": progress.flow if progress else "",
            "phase": progress.phase if progress else "",
            "latest_checkpoint": {
                "step": latest_cp.step,
                "scope": latest_cp.scope.kind,
                "seq": latest_cp.seq,
            }
            if latest_cp
            else None,
            "has_last_commit": bool(last_commit),
            "awaiting_confirmation": self._pending_checkpoint_payload(pending_checkpoint),
        }

    def ask_user(self) -> _DummyAskUser:
        """
        获取用户询问处理器
        
        返回 _DummyAskUser 对象，允许外部设置回调函数
        来处理需要用户确认的场景（如检查点确认）。
        
        Returns:
            _DummyAskUser 占位对象，可调用其 set_handler() 方法
        """
        return self._ask_user

    def configured_providers(self) -> list[str]:
        """
        获取所有已配置的 LLM 服务商列表
        
        从配置中读取并返回排序后的服务商名称列表。
        
        Returns:
            已配置的服务商名称列表，按字母排序
            例如：["deepseek", "openai", "qwen"]
        """
        return sorted(self.cfg.providers.keys())

    def configured_models(self, provider: str) -> list[str]:
        """
        获取指定服务商支持的模型列表
        
        Args:
            provider: 服务商名称（如 openai、deepseek）
            
        Returns:
            该服务商下配置的模型名称列表
            
        Raises:
            KeyError: 如果 provider 未配置
        """
        return self.cfg.candidate_models(provider)

    def current_model_selection(self, role: str = "default") -> tuple[str, str, bool]:
        """
        获取当前选择的模型信息
        
        支持查询全局默认模型或特定角色的模型配置。
        
        Args:
            role: 角色名称
                  - "default" 或 "": 查询全局默认模型
                  - "coordinator"/"architect"/"writer"/"editor": 查询角色专属模型
                  
        Returns:
            三元组 (provider, model, is_role_specific):
            - provider: 服务商名称
            - model: 模型名称
            - is_role_specific: 是否使用了角色专属配置（True 表示该角色有独立配置）
            
        Example:
            # 查询全局默认
            provider, model, is_role = host.current_model_selection()
            # ("deepseek", "deepseek-chat", False)
            
            # 查询 writer 角色
            provider, model, is_role = host.current_model_selection("writer")
            # ("openai", "gpt-4", True)  ← writer 用了更强的模型
        """
        if role and role != "default":
            rc = self.cfg.roles.get(role)
            if rc:
                return rc.provider, rc.model, True
        return self.cfg.provider, self.cfg.model, False

    def co_create_reply(self, history: list[dict[str, str]], on_delta=None) -> dict[str, object]:
        """
        共创模式回复生成
        
        在"人机共创"场景下使用，让 LLM 分析用户的对话历史，
        生成一段友好的回复 + 可直接用于开始创作的 prompt。
        
        工作流程：
        1. 从对话历史中提取用户消息
        2. 构建 LLM 请求（system prompt 为 coordinator 提示词）
        3. 先尝试流式调用（支持实时显示生成过程）
        4. 如果流式结果为空，回退到同步调用
        5. 尝试从响应中解析 JSON 格式的结构化数据
        6. 如果 JSON 解析失败，将原始文本作为 message 返回
        
        Args:
            history: 对话历史列表，每项包含 role 和 content
                     例如：[{"role": "user", "content": "我想写一本仙侠小说"},
                            {"role": "assistant", "content": "好的，请告诉我..."}]
            on_delta: 可选的流式回调函数，当有新文本片段时调用
                      签名：on_delta(delta_text: str) -> None
                      
        Returns:
            包含三个字段的字典：
            - message: 给用户的友好回复文本
            - prompt: 可用于 start() 的创作提示词（可能为空）
            - ready: 是否准备好开始创作（True/False）
            
        Raises:
            ValueError: 如果对话历史中没有用户消息
            ValueError: 如果 LLM API Key 未配置
            RuntimeError: 如果 LLM 返回了空响应
            
        Example:
            reply = host.co_create_reply([
                {"role": "user", "content": "帮我写一个修真故事"}
            ])
            
            print(reply["message"])  
            # "好的！修真题材很有意思。根据你的想法，我建议..."
            
            print(reply["prompt"])   
            # "创作一部东方玄幻修真小说，主角林凡是一个..."
            
            if reply["ready"]:
                host.start(reply["prompt"])
        """
        user_text = "\n".join(
            item.get("content", "") for item in history if item.get("role") == "user"
        ).strip()
        if not user_text:
            raise ValueError("co-create history is empty")

        pc = self.cfg.providers.get(self.cfg.provider)
        if pc is None or not pc.api_key:
            raise ValueError("provider api_key 未配置")
        client = OpenAICompatClient(api_key=pc.api_key, model=self.cfg.model, base_url=pc.base_url, timeout=120.0)
        from ainovel_py.assets import load_bundle
        bundle = load_bundle(self.cfg.style)
        prompt = bundle.prompts.get("coordinator") or (
            "你在进行小说共创规划。请先给用户一段简短回复，再提供一段可直接开始写作的创作 prompt。"
            "输出格式必须为 JSON: {\"message\": string, \"prompt\": string, \"ready\": bool}。"
        )
        user_prompt = "\n".join(f"{item.get('role', 'user')}: {item.get('content', '')}" for item in history)
        raw = client.complete_stream(prompt, user_prompt, on_delta=on_delta, temperature=0.6)
        if not (raw or "").strip():
            raw = client.complete(prompt, user_prompt, temperature=0.6)
        try:
            data = self._extract_json_object(raw)
            return {
                "message": str(data.get("message", "") or ""),
                "prompt": str(data.get("prompt", "") or ""),
                "ready": bool(data.get("ready", False)),
            }
        except ValueError:
            text = (raw or "").strip()
            if not text:
                raise RuntimeError("assistant reply is empty")
            return {
                "message": text,
                "prompt": "",
                "ready": False,
            }

    @staticmethod
    def _extract_json_object(raw: str) -> dict[str, object]:
        """
        从 LLM 响应中提取 JSON 对象
        
        LLM 返回的文本可能包裹在 markdown 代码块中，
        或者前后有多余的文字，此方法尝试多种策略提取有效的 JSON。
        
        提取策略（按优先级）：
        1. 直接解析完整文本
        2. 如果以 ``` 开头，提取代码块内的内容
        3. 查找第一个 { 和最后一个 }，提取中间的内容
        
        Args:
            raw: LLM 返回的原始文本
            
        Returns:
            解析成功的 Python 字典
            
        Raises:
            ValueError: 如果无法从任何策略中提取有效 JSON
        """
        text = (raw or "").strip()
        if not text:
            raise ValueError("empty co-create reply")
        candidates = [text]
        if text.startswith("```"):
            lines = text.splitlines()
            if len(lines) >= 3:
                fence_body = "\n".join(lines[1:-1]).strip()
                if fence_body:
                    candidates.insert(0, fence_body)
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            candidates.append(text[start : end + 1])
        for candidate in candidates:
            try:
                data = json.loads(candidate)
                if isinstance(data, dict):
                    return data
            except Exception:
                continue
        raise ValueError("co-create reply is not valid JSON")

    def switch_model(self, role: str, provider: str, model: str) -> None:
        """
        动态切换使用的 LLM 模型
        
        允许在运行过程中（非创作进行时）切换到不同的模型。
        可以切换全局默认模型，也可以只切换某个角色的模型。
        
        切换后的影响：
        - 更新配置中的 provider/model
        - 重新构建协调器循环（build_coordinator_loop）
          这意味着所有工具和状态机会使用新模型
        - 发送 SYSTEM 事件记录切换操作
        
        适用场景：
        - 用户发现当前模型效果不好，想换个试试
        - 不同阶段用不同模型（规划用强模型，写作用快模型）
        - 成本控制（白天用贵模型，晚上用便宜模型）
        
        Args:
            role: 目标角色
                 - "default" 或 "": 切换全局默认模型
                 - "coordinator"/"architect"/"writer"/"editor": 只切换该角色的模型
            provider: 新的服务商名称（必须在 providers 中已配置）
            model: 新的模型名称
            
        Raises:
            ValueError: provider 或 model 为空
            ValueError: provider 未在配置中注册
            ValueError: role 不是 "default" 且未在 roles 中配置
            
        Example:
            # 切换全局默认模型到 GPT-4
            host.switch_model("default", "openai", "gpt-4")
            
            # 只让 Writer 角色用 DeepSeek（其他角色不变）
            host.switch_model("writer", "deepseek", "deepseek-chat")
        """
        if not provider or not model:
            raise ValueError("provider and model are required")
        if provider not in self.cfg.providers:
            raise ValueError(f"provider {provider} is not configured")
        if role and role != "default":
            rc = self.cfg.roles.get(role)
            if rc is None:
                raise ValueError(f"role {role} is not configured")
            rc.provider = provider
            rc.model = model
            self.cfg.roles[role] = rc
        else:
            self.cfg.provider = provider
            self.cfg.model = model

        self.loop = build_coordinator_loop(
            self.cfg,
            self.store,
            emit_event=self._emit_event,
            emit_stream=self._emit_stream_chunk,
        )
        self._emit_event(Event(time=datetime.now(), category="SYSTEM", summary=f"模型已切换：{role or 'default'} -> {provider}/{model}", level="info"))

    def snapshot(self) -> UISnapshot:
        """
        生成 UI 快照数据（面向前端展示）
        
        与 report() 的区别：
        - report(): 返回精简的结构化数据，供后端/API 使用
        - snapshot(): 返回丰富的展示数据，供前端 UI 渲染
        
        快照包含的信息：
        
        基本信息：
        - provider/model_name/style: 配置信息
        - runtime_state/status_label: 当前状态及可读标签
        - backend: 后端类型标识
        
        进度详情：
        - phase/flow/current_chapter/total_chapters: 详细进度
        - completed_count/total_word_count: 统计数据
        - pending_rewrites/rewrite_reason: 重写相关信息
        
        内容预览（截断显示）：
        - premise: 故事前提（前240字符）
        - outline: 前8章的大纲预览
        - characters: 前12个角色列表
        - recent_summaries: 最近3章的摘要
        - last_review_summary: 最新一章的评审结果
        
        上下文用量：
        - context_tokens: 估算的 Token 使用量
        - context_percent: 上下文窗口使用百分比
        - context_window: 总窗口大小
        
        状态信息：
        - pending_steer: 待处理的用户干预指令
        - agent_status: Agent 状态列表
        
        Returns:
            UISnapshot 数据对象，包含上述所有字段
            
        Note:
            所有文本字段都有长度限制（截断），避免传输过大数据
        """
        progress = self.store.progress.load()
        meta = self.store.run_meta.load()
        snap = UISnapshot(
            provider=self.cfg.provider,
            model_name=self.cfg.model,
            style=self.cfg.style,
            runtime_state=self.lifecycle,
            status_label=self._derive_status_label(progress),
            backend=f"llm/langgraph",
            context_window=self.cfg.context_window,
        )
        if progress:
            snap.phase = progress.phase
            snap.flow = progress.flow
            snap.current_chapter = progress.current_chapter
            snap.total_chapters = progress.total_chapters
            snap.completed_count = len(progress.completed_chapters)
            snap.total_word_count = progress.total_word_count
            snap.pending_rewrites = list(progress.pending_rewrites)
            snap.rewrite_reason = progress.rewrite_reason
        if meta:
            snap.pending_steer = meta.pending_steer

        premise = self.store.outline.load_premise()
        if premise:
            snap.premise = premise[:240]
        snap.outline = [
            {"chapter": item.chapter, "title": item.title, "core_event": item.core_event}
            for item in self.store.outline.load_outline()[:8]
        ]
        snap.characters = [
            f"{c.name}（{c.role}）" if c.role else c.name
            for c in self.store.characters.load()[:12]
        ]
        if progress and progress.completed_chapters:
            for ch in progress.completed_chapters[-3:]:
                summary = self.store.summaries.load_summary(ch)
                if summary:
                    snap.recent_summaries.append(f"第{ch}章: {summary.summary[:80]}")
            review = self.store.world.load_review(progress.completed_chapters[-1])
            if review:
                snap.last_review_summary = f"{review.verdict}: {review.summary[:80]}"

        if progress:
            approx_tokens = max(progress.total_word_count // 2, 0)
            snap.context_tokens = approx_tokens
            if self.cfg.context_window > 0:
                snap.context_percent = round((approx_tokens / self.cfg.context_window) * 100, 2)
        snap.agent_status = ["coordinator: ready", f"backend: llm/langgraph"]
        return snap

    def _derive_status_label(self, progress) -> str:
        """
        根据当前状态推导人类可读的状态标签
        
        将内部的 lifecycle/phase/flow 等技术状态转换为
        前端可以展示的友好标签。
        
        状态优先级判断规则（从高到低）：
        1. COMPLETE: 创作已完成（终态，最高优先级）
        2. AWAITING_CONFIRMATION: 正在等待用户确认检查点
        3. REVIEW: 正在进行质量评审
        4. REWRITE: 正在进行重写或打磨
        5. RUNNING: 正在运行中
        6. READY: 就绪（默认状态）
        
        Args:
            progress: Progress 对象（可能为 None）
            
        Returns:
            状态标签字符串，取值范围为：
            "COMPLETE" / "AWAITING_CONFIRMATION" / "REVIEW" /
            "REWRITE" / "RUNNING" / "READY"
        """
        if progress and progress.phase == Phase.COMPLETE:
            return "COMPLETE"
        if self.store.signals.load_pending_checkpoint() is not None:
            return "AWAITING_CONFIRMATION"
        if progress and progress.flow == "reviewing":
            return "REVIEW"
        if progress and progress.flow in {"rewriting", "polishing"}:
            return "REWRITE"
        if self.lifecycle == "running":
            return "RUNNING"
        return "READY"

    def replay_queue(self, after_seq: int) -> list[RuntimeQueueItem]:
        """
        重放事件队列（从持久化存储读取）
        
        用于 SSE 断线重连时补发丢失的事件。
        与内存队列不同，这里从磁盘读取完整的持久化历史。
        
        Args:
            after_seq: 起始序列号，只返回 seq 大于此值的事件
                      首次调用传 0，后续传上次收到的最大 seq
                      
        Returns:
            RuntimeQueueItem 列表，按 seq 升序排列
            
        Note:
            此方法读取的是持久化到磁盘的事件，不受内存队列大小限制
        """
        return self.store.runtime.load_queue_after(after_seq)

    def start(self, prompt: str) -> None:
        """
        开始新的创作（便捷方法）
        
        内部调用 start_prepared()，先对 prompt 进行预处理。
        
        Args:
            prompt: 用户的创作提示词，例如："写一本仙侠修真小说"
        """
        self.start_prepared(build_start_prompt(prompt))

    def start_prepared(self, prompt_text: str) -> None:
        """
        开始新的创作（核心方法）
        
        执行完整的"启动新创作"流程，包括：
        
        1. 前置校验
           - 检查是否已在运行中（防止重复启动）
           - 检查 prompt 是否为空
           
        2. 环境重置
           - 重置运行时队列（清空旧事件）
           - 初始化进度跟踪器
           - 清除待处理的提交信号
           - 清除过期的信号
           - 重置检查点状态
           
        3. 状态更新
           - 将 lifecycle 设为 "running"
           - 重置恢复计数器
           
        4. 事件广播
           - 发送"开始创作"系统事件
           - 发送清空信号（通知前端清空显示区域）
           
        5. 启动协调器
           - 调用 loop.start(prompt) 进入主循环
           - loop.start() 内部会驱动 LangGraph 状态机执行
           - 状态机会依次执行：load_context → plan → draft → commit → review → ...
           - wait_idle() 阻塞等待直到循环结束
           
        6. 收尾工作
           - 调用 _mark_idle_or_complete() 更新最终状态
           
        Args:
            prompt_text: 经过预处理的完整提示词
                        通常由 build_start_prompt() 生成
                        
        Raises:
            ValueError: 如果已在运行中（lifecycle == "running"）
            ValueError: 如果 prompt_text 为空
            
        Note:
            此方法是阻塞的！它会等到整个创作循环结束后才返回。
            对于长时间的创作任务，应该在独立的线程中调用（WorkerManager 就是这么做的）
        """
        if self.lifecycle == "running":
            raise ValueError("already running")
        text = prompt_text.strip()
        if not text:
            raise ValueError("prompt is required")

        self.store.runtime.reset()
        self.store.progress.init("", 0)
        self.store.signals.clear_pending_commit()
        self.store.signals.clear_stale_signals()
        self.store.checkpoints.reset()
        self.lifecycle = "running"
        self.idle_resume_count = 0

        self._emit_event(Event(time=datetime.now(), category="SYSTEM", summary="开始创作", level="info"))
        self._emit_clear()
        self.loop.start(text)
        self.loop.wait_idle()
        self._mark_idle_or_complete()

    def resume(self) -> str:
        """
        从断点恢复创作
        
        当之前的创作被暂停（pause）或异常中断后，
        使用此方法从上次的位置继续。
        
        执行流程：
        1. 检查是否已在运行中
        2. 调用 build_resume_prompt() 构建恢复用的 prompt
           - 会读取当前的进度状态、最新检查点等信息
           - 生成包含上下文的恢复指令
        3. 如果无法构建恢复 prompt（没有有效断点），返回空字符串
        4. 设置 lifecycle 为 "running"
        5. 广播"恢复创作"事件
        6. 调用 loop.resume(prompt) 执行恢复
        7. 等待循环结束并更新最终状态
        
        Returns:
            恢复的标签描述字符串（用于日志和调试）
            如果无法恢复则返回空字符串 ""
            
        Raises:
            ValueError: 如果已在运行中
            
        Example:
            label = host.resume()
            if label:
                print(f"已恢复：{label}")
            else:
                print("没有可恢复的断点")
        """
        if self.lifecycle == "running":
            raise ValueError("already running")
        prompt, label = build_resume_prompt(self.store)
        if not label:
            return ""

        self.lifecycle = "running"
        self.idle_resume_count = 0
        self._emit_event(Event(time=datetime.now(), category="SYSTEM", summary=f"恢复创作: {label}", level="info"))
        self.loop.resume(prompt)
        self.loop.wait_idle()
        self._mark_idle_or_complete()
        return label

    def continue_run(self, text: str) -> None:
        """
        继续运行或追加内容
        
        用于两种场景：
        1. 检查点确认后继续：text = "__RUN_CONTINUE__"
        2. 用户追加新的创作指令：text = "接下来写个番外篇"
        
        与 resume() 的区别：
        - resume(): 从 Store 读取断点自动构建 prompt
        - continue_run(): 直接使用用户提供的 text 作为 prompt
        
        特殊处理：
        - 如果当前不是 running 状态，会自动设为 running
        - 调用 loop.follow_up(content) 而非 loop.start() 或 loop.resume()
          follow_up() 会在现有上下文基础上追加执行
        
        Args:
            text: 要执行的文本内容
                  特殊值 "__RUN_CONTINUE__" 表示确认检查点后继续
                  
        Raises:
            ValueError: 如果 text 为空
        """
        content = text.strip()
        if not content:
            raise ValueError("text is required")

        if self.lifecycle != "running":
            self.lifecycle = "running"
        self.loop.follow_up(content)
        self.loop.wait_idle()
        self._mark_idle_or_complete()

    def steer(self, text: str) -> None:
        """
        用户干预（方向指导）
        
        允许用户在不停止创作的情况下插入创作指导，
        影响后续章节的写作方向。
        
        两种处理模式：
        
        1. 运行中干预（lifecycle == "running"）：
           - 立即发送事件广播，通知协调器和前端
           - 干预内容会在下一轮循环中被 Coordinator 处理
           - 不会立即改变当前正在生成的章节
           
        2. 待命干预（lifecycle != "running"）：
           - 将干预内容保存到 run_meta.pending_steer
           - 下次调用 start() 或 resume() 时自动注入到 prompt 中
           - 适合提前规划但还没开始创作的场景
           
        Args:
            text: 干预内容，例如：
                  - "第11章让主角受伤"
                  - "加快节奏，增加冲突"
                  - "引入一个新的反派角色"
                  
        Example:
            # 场景1：创作进行中，想让后面剧情转向
            host.steer("接下来的三章让主角发现身世秘密")
            
            # 场景2：还没开始，先设定好方向
            host.steer("结局要是悲剧，主角牺牲自己拯救世界")
            # ... 之后调用 host.start() 时会自动带上这个方向
        """
        content = text.strip()
        if not content:
            return
        if self.lifecycle == "running":
            self._emit_event(Event(time=datetime.now(), category="SYSTEM", summary=f"干预已提交: {content[:40]}", level="info"))
            return
        self.store.run_meta.set_pending_steer(content)
        self._emit_event(Event(time=datetime.now(), category="SYSTEM", summary="干预已保存，下次启动时生效", level="info"))

    def abort(self) -> bool:
        """
        中止当前运行（暂停）
        
        请求停止当前正在进行的创作循环。
        注意：这不是立即终止，而是"优雅退出"：
        
        1. 检查当前是否在运行中
           - 如果不在运行中，返回 False（无需中止）
           
        2. 更新状态
           - 将 lifecycle 从 "running" 改为 "paused"
           
        3. 通知协调器
           - 调用 loop.abort() 设置中止标志
           - 协调器会在当前步骤完成后检测到此标志并停止
           - 不会中断正在进行的 LLM 调用（避免数据不一致）
           
        4. 广播事件
           - 发送"手动暂停"警告事件
           - 向 done_ch 队列发送完成信号
           
        Returns:
            True: 成功发起中止请求
            False: 当前不在运行中，无需中止
            
        Note:
            abort() 后可以通过 resume() 或 continue_run() 恢复
            如果想永久取消，应使用 service.cancel_run() 
        """
        if self.lifecycle != "running":
            return False
        self.lifecycle = "paused"
        self.loop.abort()
        self._emit_event(Event(time=datetime.now(), category="SYSTEM", summary="用户手动暂停当前创作", level="warn"))
        self._safe_put(self.done_ch, True)
        return True

    def close(self) -> None:
        """
        关闭 Host 实例
        
        标记 Host 为已关闭状态，释放资源。
        
        目前仅设置 _closed 标志，未来可能会扩展为：
        - 取消所有待处理的队列项
        - 关闭 Store 连接
        - 终止后台线程
        """
        self._closed = True

    def _mark_idle_or_complete(self) -> None:
        """
        标记最终状态（运行循环结束后的收尾工作）
        
        当 loop.start()/resume()/follow_up() 返回后调用，
        根据当前进度决定最终的 lifecycle 状态。
        
        状态判断逻辑：
        
        1. COMPLETED（创作完成）：
           - progress.phase == Phase.COMPLETE
           - 整本小说已经写完
           - 终态，不能再 start/resume
           
        2. PAUSED（等待确认）：
           - 存在 pending_checkpoint（检查点暂停机制触发）
           - 每 N 章自动暂停一次，等待用户确认后再继续
           - 可以通过 continue_run("__RUN_CONTINUE__") 恢复
           
        3. IDLE（空闲）：
           - 其他情况（正常停止、无检查点等）
           - 可以再次 start() 开始新创作
           
        无论哪种状态，都会：
        - 发送对应的生命周期事件
        - 向 done_ch 队列放入完成信号
        """
        progress = self.store.progress.load()
        if progress and progress.phase == Phase.COMPLETE:
            self.lifecycle = "completed"
            self._emit_event(Event(time=datetime.now(), category="SYSTEM", summary="创作完成", level="success"))
        else:
            if self.store.signals.load_pending_checkpoint() is not None:
                self.lifecycle = "paused"
                self._emit_event(Event(time=datetime.now(), category="SYSTEM", summary="等待用户确认继续编写", level="info"))
            else:
                self.lifecycle = "idle"
                self._emit_event(Event(time=datetime.now(), category="SYSTEM", summary="Coordinator 停止", level="warn"))
        self._safe_put(self.done_ch, True)

    def _append_runtime_item(self, item: RuntimeQueueItem) -> None:
        """
        向持久化运行时队列追加事件
        
        将事件写入磁盘存储，用于：
        - 断线重连时恢复丢失的事件
        - 调试时查看完整的历史记录
        
        Args:
            item: 运行时队列项
        """
        self.store.runtime.append_queue(item)

    def _append_runtime_stream_chunk(self, channel: str, delta: str) -> None:
        """
        将流式输出片段包装为运行时事件并持久化
        
        Args:
            channel: 输出通道（"content" 或 "thinking"）
            delta: 文本片段
        """
        self._append_runtime_item(
            RuntimeQueueItem(
                kind=RuntimeQueueKind.STREAM_CHUNK,
                priority=RuntimeQueuePriority.BACKGROUND,
                payload={"channel": channel, "delta": delta},
            )
        )

    def emit_checkpoint_pending(self, pending: PendingRunCheckpoint) -> None:
        """
        发送"等待检查点确认"事件
        
        当创作达到检查点（如每写完 5 章）时调用，
        通知前端需要用户确认才能继续。
        
        同时做两件事：
        1. 写入持久化运行时队列（用于 SSE 推送和历史恢复）
        2. 放入内存 events 队列（用于实时消费）
        
        Args:
            pending: 待确认的检查点信息
                    - pause_after_chapter: 已完成的章节数
                    - next_chapter: 下一个要写的章节
                    - completed_count: 总完成数
                    - status: 检查点状态
        """
        payload = self._pending_checkpoint_payload(pending)
        self._append_runtime_item(
            RuntimeQueueItem(
                kind=RuntimeQueueKind.UI_EVENT,
                priority=RuntimeQueuePriority.CONTROL,
                category="RUN",
                summary=f"已完成第{pending.pause_after_chapter}章，等待用户确认继续",
                payload={"level": "info", "event": "run.awaiting_confirmation", "awaiting_confirmation": payload},
            )
        )
        self._safe_put(self.events, Event(time=datetime.now(), category="RUN", summary=f"已完成第{pending.pause_after_chapter}章，等待用户确认继续", level="info"))

    @staticmethod
    def _pending_checkpoint_payload(pending: PendingRunCheckpoint | None) -> dict[str, object] | None:
        """
        将 PendingRunCheckpoint 转换为可序列化的字典
        
        Args:
            pending: 检查点对象，可能为 None
            
        Returns:
            字典形式的检查点数据，如果 pending 为 None 则返回 None
        """
        if pending is None:
            return None
        return {
            "pause_after_chapter": pending.pause_after_chapter,
            "next_chapter": pending.next_chapter,
            "completed_count": pending.completed_count,
            "status": pending.status,
        }

    def _emit_event(self, ev: Event) -> None:
        """
        发射系统事件（核心事件发射方法）
        
        所有系统事件都通过此方法统一发射，
        同时写入两个目的地：
        
        1. 内存队列 (self.events)：供实时消费者（SSE 推送）即时读取
        2. 持久化存储 (store.runtime)：供断线重连和事后审计
        
        Args:
            ev: Event 事件对象，包含时间戳、类别、摘要、级别等
        """
        self._safe_put(self.events, ev)
        self._append_runtime_item(
            RuntimeQueueItem(
                kind=RuntimeQueueKind.UI_EVENT,
                priority=RuntimeQueuePriority.BACKGROUND,
                category=ev.category,
                summary=ev.summary,
                payload={"level": ev.level},
            )
        )

    def _emit_delta(self, channel: str, delta: str) -> None:
        """
        发射流式输出增量（底层方法）
        
        将文本片段放入流式输出队列。
        
        Args:
            channel: 通道标识（"content" 或 "thinking"）
            delta: 文本片段内容
        """
        if not delta:
            return
        self._safe_put(self.stream_ch, StreamChunk(channel=channel, delta=delta))

    def _emit_stream_chunk(self, channel: str, text: str) -> None:
        """
        发射流式文本块（带归一化和持久化）
        
        对 _emit_delta 的增强版本：
        1. 归一化 channel 名称（只允许 content/thinking）
        2. 同时写入持久化存储
        
        Args:
            channel: 原始通道名称
            text: 文本内容
        """
        channel_norm = (channel or "content").strip().lower()
        if channel_norm not in {"content", "thinking"}:
            channel_norm = "content"
        self._emit_delta(channel_norm, text)
        self._append_runtime_stream_chunk(channel_norm, text)

    def _emit_stream_text(self, text: str) -> None:
        """
        便捷方法：向 content 通道发射文本
        
        Args:
            text: 文本内容
        """
        self._emit_stream_chunk("content", text)

    def _emit_clear(self) -> None:
        """
        发射清空信号
        
        通知前端清空显示区域（通常在新一轮创作开始前调用）。
        同时写入持久化存储和内存队列。
        """
        self._append_runtime_item(
            RuntimeQueueItem(
                kind=RuntimeQueueKind.STREAM_CLEAR,
                priority=RuntimeQueuePriority.BACKGROUND,
                payload={},
            )
        )
        self._safe_put(self.clear_ch, True)

    @staticmethod
    def _safe_put(queue: asyncio.Queue, value: object) -> None:
        """
        安全地向队列放入元素（带背压保护）
        
        解决的核心问题：
        LLM 生成速度 >> 前端消费速度 → 内存队列堆积 → OOM
        
        处理策略（三级降级）：
        
        Level 1: 尝试正常放入
        - 使用 put_nowait() 非阻塞尝试
        - 如果队列未满，成功放入，结束
        
        Level 2: 丢弃最旧的元素
        - 如果队列满了（QueueFull 异常）
        - 尝试 get_nowait() 移除队首（最旧的）元素
        - 然后重新尝试 put_nowait()
        
        Level 3: 静默丢弃
        - 如果还是放不下（极端情况）
        - 直接放弃，不抛异常
        - 保证系统稳定运行优先于数据完整性
        
        设计理念：
        - 对于流式输出：丢中间的 token 比崩掉好
        - 对于事件：丢旧事件比丢新事件好
        - 对于控制信号：done_ch/clear_ch 很小，一般不会满
        
        Args:
            queue: 目标 asyncio.Queue
            value: 要放入的值
            
        Note:
            此方法是静态方法，不依赖实例状态
        """
        try:
            queue.put_nowait(value)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except Exception:
                pass
            try:
                queue.put_nowait(value)
            except Exception:
                pass
