"""
内部 API 路由模块

提供 RESTful API 接口，供 Java 平台层调用 Python Agent 运行时。
所有接口都需要内部认证（require_internal_auth）。

主要功能：
- 运行管理：创建/暂停/恢复/取消小说创作任务
- 事件流：SSE 实时推送创作过程中的事件
- 数据查询：获取章节内容、运行状态、产物列表
- 健康检查：监控服务状态

接口前缀：/internal/v1
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ainovel_py.internal_api.deps import get_run_service, require_internal_auth
from ainovel_py.internal_api.dto import CreateRunRequest, InstructionRequest, PauseRunRequest, ResumeRunRequest
from ainovel_py.internal_api.errors import ApiError
from ainovel_py.internal_api.mappers import envelope, map_artifacts, map_chapter, map_create_run, map_event, map_events, map_instruction_ack, map_pause_ack, map_run
from ainovel_py.internal_api.response_dto import AckPayload, ArtifactListPayload, ChapterPayload, CreateRunPayload, Envelope, ErrorResponse, EventsPagePayload, HealthPayload, RunListPayload, RunPayload
from ainovel_py.internal_api.service import RunService


router = APIRouter(prefix="/internal/v1", dependencies=[Depends(require_internal_auth)])


def _format_sse_event(item: dict[str, object]) -> str:
    """
    格式化 SSE（Server-Sent Events）事件
    
    将事件字典转换为 SSE 协议格式：
    event: {event_type}
    data: {json_data}
    
    Args:
        item: 事件数据字典，必须包含 type 字段
        
    Returns:
        SSE 格式的字符串
    """
    event_type = str(item.get("type", "ui.event") or "ui.event")
    import json
    return f"event: {event_type}\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"


@router.post("/runs", response_model=Envelope[CreateRunPayload], responses={401: {"model": ErrorResponse}, 409: {"model": ErrorResponse}})
async def create_run(req: CreateRunRequest, service: RunService = Depends(get_run_service)) -> dict[str, object]:
    """
    创建新的小说创作运行实例
    
    触发流程：
    1. 解析请求中的故事配置（前提、角色、大纲等）
    2. 构建系统配置（模型选择、风格等）
    3. 初始化 Host 主机控制器（包含 Store、AgentRunner、LangGraph）
    4. 将初始数据存入 Store（前提、角色等）
    5. 注册 RunSession 到 Registry
    6. 下发 start 任务到 WorkerManager 队列（异步执行）
    
    Args:
        req: 创建运行请求体，包含：
            - run_id: 唯一运行标识
            - input.prompt: 用户输入的创作提示词
            - story: 故事配置（story_id、前提、角色列表等）
            - config: 模型配置（provider、model、style 等）
            
    Returns:
        包含 run_id 和初始状态报告的信封响应
        
    Raises:
        400: prompt 为空或参数无效
        401: 认证失败
        409: run_id 已存在（幂等处理，直接返回已有实例）
        
    Example:
        POST /internal/v1/runs
        {
            "run_id": "uuid-1234",
            "input": {"prompt": "写一本仙侠修真小说"},
            "story": {"story_id": "story-001"},
            "config": {"provider": "deepseek", "model": "deepseek-chat"}
        }
    """
    session = service.create_run(req)
    report = session.host.report()
    return envelope(map_create_run(session, report))


@router.get("/health", response_model=Envelope[HealthPayload], responses={401: {"model": ErrorResponse}})
async def health(request: Request) -> dict[str, object]:
    """
    健康检查端点
    
    用于 Java 平台层检测 Python 服务是否正常运行，
    以及当前活跃的运行实例数量。
    
    Args:
        request: FastAPI 请求对象（用于访问 app.state）
        
    Returns:
        服务状态信息：
        - status: 固定为 "ok"
        - host: 监听地址
        - port: 监听端口
        - run_count: 当前注册的运行实例数
        
    Example:
        GET /internal/v1/health
        Response: {"status": "ok", "host": "127.0.0.1", "port": 8900, "run_count": 3}
    """
    settings = request.app.state.settings
    registry = request.app.state.run_registry
    return envelope({
        "status": "ok",
        "host": settings.host,
        "port": settings.port,
        "run_count": len(registry.list()),
    })


@router.get("/runs", response_model=Envelope[RunListPayload], responses={401: {"model": ErrorResponse}})
async def list_runs(
    status: str = Query(default=""),
    story_id: str = Query(default=""),
    service: RunService = Depends(get_run_service),
) -> dict[str, object]:
    """
    获取运行实例列表
    
    支持按状态和故事 ID 过滤。Java 前端用此接口展示"我的作品列表"。
    
    Args:
        status: 可选的状态过滤值（如 running/completed/paused/failed）
                为空则返回所有状态的运行
        story_id: 可选的故事 ID 过滤
                  为空则返回所有故事的运行
        service: 注入的 RunService 实例
        
    Returns:
        运行实例列表，每项包含：
        - run_id: 运行标识
        - story_id: 故事标识
        - lifecycle: 当前生命周期状态
        - completed_chapters: 已完成章节数
        - current_chapter: 当前进度
        - created_at: 创建时间
        
    Example:
        GET /internal/v1/runs?status=running&story_id=story-001
    """
    items = [map_run(session, report) for session, report in service.list_runs(status=status, story_id=story_id)]
    return envelope({"items": items})


@router.get("/runs/{run_id}", response_model=Envelope[RunPayload], responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}})
async def get_run(run_id: str, service: RunService = Depends(get_run_service)) -> dict[str, object]:
    """
    获取单个运行实例的详细信息
    
    用于 Java 前端展示某个作品的详情页面，
    包括当前进度、字数统计、使用的模型等信息。
    
    Args:
        run_id: 运行实例的唯一标识
        service: 注入的 RunService 实例
        
    Returns:
        运行实例详细信息：
        - 基本信息：run_id、story_id、output_dir
        - 配置信息：provider、model、style
        - 进度信息：lifecycle、completed_chapters、current_chapter、total_word_count
        - 流程信息：flow（当前处于哪个阶段）、phase
        - 检查点信息：latest_checkpoint
        - 状态标记：awaiting_confirmation（是否等待用户确认继续）
        
    Raises:
        404: run_id 不存在
        
    Example:
        GET /internal/v1/runs/uuid-1234
    """
    session, report = service.get_report(run_id)
    return envelope(map_run(session, report))


@router.post("/runs/{run_id}/pause", response_model=Envelope[AckPayload], responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}})
async def pause_run(run_id: str, req: PauseRunRequest, service: RunService = Depends(get_run_service)) -> dict[str, object]:
    """
    暂停正在运行的创作任务
    
    调用 Host.abort() 方法：
    1. 将 lifecycle 从 running 改为 paused
    2. 调用 loop.abort() 通知 LangGraph 状态机停止
    3. 发送 done_ch 信号通知 WorkerManager
    4. 当前正在执行的 LLM 调用不会被立即中断（安全退出）
    
    Args:
        run_id: 要暂停的运行标识
        req: 暂停请求体（当前为空，预留扩展）
        service: 注入的 RunService 实例
        
    Returns:
        操作确认 + 暂停后的最新状态报告
        
    Raises:
        404: run_id 不存在
        
    Example:
        POST /internal/v1/runs/uuid-1234/pause
    """
    _ = req
    session = service.pause_run(run_id)
    return envelope(map_pause_ack(session, session.host.report()))


@router.post("/runs/{run_id}/resume", response_model=Envelope[AckPayload], responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}})
async def resume_run(run_id: str, req: ResumeRunRequest, service: RunService = Depends(get_run_service)) -> dict[str, object]:
    """
    恢复暂停的创作任务
    
    支持两种场景：
    1. 从检查点确认恢复（decision=approve/continue）：
       - 用户确认了暂停时的检查点，使用 "__RUN_CONTINUE__" 继续下一章
    2. 从任意暂停状态恢复（无 decision 或有新 prompt）：
       - 构建 resume prompt（包含之前的上下文和进度）
       - 调用 Host.resume() 从断点恢复执行
    
    Args:
        run_id: 要恢复的运行标识
        req: 恢复请求体，包含：
            - decision: 用户决定（approve/continue/reject）
            - input.prompt: 可选的新提示词（用于 steer 场景）
            - feedback: 可选的用户反馈
        service: 注入的 RunService 实例
        
    Returns:
        操作确认 + 恢复后的最新状态报告
        
    Raises:
        400: 参数无效或决策冲突（如需要确认但未提供 decision）
        404: run_id 不存在
        409: 运行正在进行中（不能重复启动）
        
    Example:
        POST /internal/v1/runs/uuid-1234/resume
        {"decision": "continue"}
    """
    session = service.resume_run(run_id, req)
    return envelope(map_pause_ack(session, session.host.report()))


@router.post("/runs/{run_id}/cancel", response_model=Envelope[AckPayload], responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}})
async def cancel_run(run_id: str, service: RunService = Depends(get_run_service)) -> dict[str, object]:
    """
    取消运行实例（终止并标记为已取消）
    
    与 pause 的区别：
    - pause: 临时暂停，可以 resume 继续
    - cancel: 永久取消，将 state_override 设为 "canceled"
      同时取消队列中所有待执行的关联任务
    
    适用场景：
    - 用户主动删除某个作品
    - 系统检测到异常需要强制终止
    
    Args:
        run_id: 要取消的运行标识
        service: 注入的 RunService 实例
        
    Returns:
        操作确认 + 取消后的状态报告（state_override=canceled）
        
    Raises:
        404: run_id 不存在
        
    Example:
        POST /internal/v1/runs/uuid-1234/cancel
    """
    session = service.cancel_run(run_id)
    return envelope(map_pause_ack(session, session.host.report()))


@router.post("/runs/{id}/instructions", response_model=Envelope[AckPayload], responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}})
async def add_instruction(run_id: str, req: InstructionRequest, service: RunService = Depends(get_run_service)) -> dict[str, object]:
    """
    向运行实例发送指令（干预/继续/跟随）
    
    核心的人机协作接口，支持多种指令类型：
    
    1. **steer（方向干预）**：
       - 用户在非运行状态下提交创作指导
       - 例如："第11章让主角受伤"、"加快节奏"
       - 存入 run_meta.pending_steer，下次启动时注入 Prompt
       
    2. **continue（继续执行）**：
       - 用于检查点确认后继续
       - 使用 "__RUN_CONTINUE__" 特殊文本触发 continue_run()
       
    3. **follow_up（追加内容）**：
       - 在运行结束后追加新的创作指令
       - 例如："再写一个番外篇"
       - 调用 Host.follow_up() 启动新一轮循环
       
    Args:
        run_id: 目标运行标识
        req: 指令请求体，包含：
            - instruction.type: 指令类型（steer/continue/follow_up）
            - instruction.text: 指令文本内容
            - instruction.decision: 决策（approve/continue/reject）
            - instruction.feedback: 反馈内容
        service: 注入的 RunService 实例
        
    Returns:
        操作确认 + 最新状态报告
        
    Raises:
        400: 缺少必要参数或决策冲突
        404: run_id 不存在
        409: 运行忙（某些指令类型不允许在运行中调用）
        
    Example:
        POST /internal/v1/runs/uuid-1234/instructions
        {
            "instruction": {
                "type": "steer",
                "text": "接下来让主角发现隐藏身份"
            }
        }
    """
    session = service.add_instruction(run_id, req)
    return envelope(map_instruction_ack(session, session.host.report()))


@router.get("/runs/{run_id}/events", response_model=Envelope[EventsPagePayload], responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}})
async def get_events(
    run_id: str,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: RunService = Depends(get_run_service),
) -> dict[str, object]:
    """
    分页获取运行事件历史（轮询模式）
    
    用于前端以轮询方式获取创作过程中产生的事件。
    事件包括：工具调用、状态变化、错误警告、LLM 输出片段等。
    
    与 stream 接口的区别：
    - 本接口：一次性返回指定范围的事件（适合断线重连、首次加载）
    - stream 接口：长连接持续推送（适合实时监听）
    
    Args:
        run_id: 运行标识
        after_seq: 起始序列号（只返回 seq > after_seq 的事件）
                   首次调用传 0，后续传上次收到的最大 seq
        limit: 返回的最大事件数量（1-500，默认100）
        service: 注入的 RunService 实例
        
    Returns:
        分页事件数据：
        - items: 事件列表（按 seq 升序排列）
        - has_more: 是否还有更多事件（用于分页加载）
        - after_seq: 本次查询的起始位置
        - limit: 本次查询的限制数量
        - total_available: 符合条件的总事件数
        
    Event 数据结构示例：
        {
            "seq": 42,
            "type": "ui.event",
            "timestamp": "2024-01-15T10:30:00Z",
            "category": "TOOL",
            "summary": "调用 plan_chapter (ch5)",
            "payload": {"level": "info"}
        }
        
    Raises:
        404: run_id 不存在
        
    Example:
        GET /internal/v1/runs/uuid-1234/events?after_seq=35&limit=50
    """
    session, items, total = service.get_events(run_id, after_seq, limit)
    has_more = total > len(items)
    return envelope(map_events(run_id, items, has_more, after_seq=after_seq, limit=limit, total_available=total))


@router.get("/runs/{run_id}/events/stream", responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}})
async def stream_events(
    run_id: str,
    after_seq: int = Query(default=0, ge=0),
    service: RunService = Depends(get_run_service),
) -> StreamingResponse:
    """
    SSE 实时事件流（长连接推送模式）
    
    提供 Server-Sent Events 流式接口，用于前端实时接收创作过程事件。
    相比轮询方式，延迟更低、更节省资源。
    
    工作机制：
    1. 前端建立 SSE 连接（EventSource 或 fetch + ReadableStream）
    2. 后端进入异步生成器循环，每 350ms 轮询一次新事件
    3. 有新事件时以 SSE format 推送给前端
    4. 当运行结束（completed/paused）或失败（failed/canceled）时关闭连接
    
    断线重连策略：
    - 前端记录最后收到的 seq
    - 重连时传 after_seq=last_seq
    - 后端从持久化存储中补发丢失的事件
    
    Args:
        run_id: 运行标识
        after_seq: 起始序列号（用于断线重连，跳过已收到的事件）
        service: 注入的 RunService 实例
        
    Returns:
        StreamingResponse (Content-Type: text/event-stream)
        SSE 事件流，每条事件格式：
        ```
        event: ui.event
        data: {"seq": 43, "type": "ui.event", "summary": "...", ...}
        
        event: stream.chunk
        data: {"channel": "content", "delta": "今天天气..."}
        ```
        
    终止条件（任一满足即断开）：
    - lifecycle == "completed"（创作完成）
    - lifecycle == "paused"（用户暂停）
    - state_override == "failed"（运行失败）
    - state_override == "canceled"（用户取消）
        
    Raises:
        404: run_id 不存在（连接建立时立即抛出）
        
    Example:
        GET /internal/v1/runs/uuid-1234/events/stream?after_seq=0
        
        JavaScript 消费示例：
        const es = new EventSource('/internal/v1/runs/{id}/events/stream');
        es.addEventListener('stream.chunk', (e) => {
            const data = JSON.parse(e.data);
            editor.appendText(data.delta);  // 实时显示生成的文字
        });
        es.addEventListener('ui.event', (e) => {
            const data = JSON.parse(e.data);
            logPanel.append(data.summary);  // 显示操作日志
        });
    """
    service.get_run(run_id)

    async def _event_stream():
        current = after_seq
        while True:
            session, items, _ = service.get_events(run_id, current, 200)
            mapped = [map_event(run_id, item) for item in items]
            if mapped:
                for item in mapped:
                    current = max(current, int(item.get("seq", current) or current))
                    yield _format_sSE_event(item)
            lifecycle = str(session.host.report().get("lifecycle", "") or "idle")
            if lifecycle in {"completed", "paused"} or session.state_override in {"failed", "canceled"}:
                break
            import asyncio
            await asyncio.sleep(0.35)

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


@router.get("/runs/{run_id}/chapters/{chapter_number}", response_model=Envelope[ChapterPayload], responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}})
async def get_chapter(run_id: str, chapter_number: int, service: RunService = Depends(get_run_service)) -> dict[str, object]:
    """
    获取指定章节的完整内容
    
    用于前端展示已完成的章节正文。
    会依次查找：正式提交版本 → 草稿版本 → 404
    
    数据来源优先级：
    1. store.drafts.load_chapter_text() — 正式提交的最终版本
    2. store.drafts.load_draft() — 未提交的草稿版本（调试用）
    
    同时加载该章节的辅助信息：
    - title: 章节标题（从大纲中读取，默认为"第X章"）
    - summary: 章节摘要（AI 生成的概要）
    - review: 评审结果（Editor 的质量检查报告）
    
    Args:
        run_id: 运行标识
        chapter_number: 章节编号（从 1 开始的正整数）
        service: 注入的 RunService 实例
        
    Returns:
        章节数据：
        - title: 章节标题字符串
        - content: 章节正文（可能很长，几万字）
        - summary: 章节摘要对象（含 summary 文本、关键事件等）
        - review: 评审结果对象（含 verdict、评分、问题列表等）
        
    Raises:
        400: chapter_number <= 0
        404: 章节不存在（未创作到此章或已被删除）
        
    Example:
        GET /internal/v1/runs/uuid-1234/chapters/5
        Response: {
            "title": "第五章 初入宗门",
            "content": "清晨的雾气弥漫在山间...",
            "summary": {"summary": "主角到达宗门，通过入门测试..."},
            "review": {"verdict": "pass", "score": 85, ...}
        }
    """
    session, data = service.get_chapter(run_id, chapter_number)
    return envelope(map_chapter(run_id, chapter_number, data["title"], data["content"], data["summary"], data["review"]))


@router.get("/runs/{run_id}/artifacts", response_model=Envelope[ArtifactListPayload], responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}})
async def get_artifacts(
    run_id: str,
    type: str = Query(default=""),
    chapter: int = Query(default=0, ge=0),
    service: RunService = Depends(get_run_service),
) -> dict[str, object]:
    """
    获取运行产物的文件列表
    
    产物指创作过程中生成的各类文件：
    - outline: 大纲文件（outline.json）
    - characters: 角色定义文件（characters.json）
    - premise: 故事前提文件
    - chapter_plan: 章节规划文件
    - review: 评审报告文件
    - summary: 摘要文件
    - checkpoint: 检查点文件
    
    主要用途：
    1. Java 前端的"文件浏览器"功能
    2. 导出/下载原始文件
    3. 调试时查看中间产物
    
    Args:
        run_id: 运行标识
        type: 产物类型过滤（可选）
              为空则返回所有类型的产物
              常见值：outline/characters/premise/chapter/review/summary
        chapter: 章节号过滤（可选，仅对 chapter 类型有效）
               为空则返回所有章节的产物
        service: 注入的 RunService 实例
        
    Returns:
        产物文件列表，每项包含：
        - filename: 文件名
        - type: 产物类型
        - chapter: 关联章节（如有）
        - size: 文件大小（字节）
        - modified_time: 最后修改时间
        - path: 相对于 output_dir 的路径
        
    Example:
        # 获取所有产物
        GET /internal/v1/runs/uuid-1234/artifacts
        
        # 仅获取大纲文件
        GET /internal/v1/runs/uuid-1234/artifacts?type=outline
        
        # 获取第5章的所有相关产物
        GET /internal/v1/runs/uuid-1234/artifacts?chapter=5
    """
    session, items = service.get_artifacts(run_id, artifact_type=type, chapter=chapter)
    return envelope(map_artifacts(session.run_id, items))


def install_error_handlers(app) -> None:
    """
    安装全局异常处理器
    
    注册两类异常的统一处理逻辑，确保 API 返回一致的错误格式。
    
    处理的异常类型：
    
    1. ApiError（业务异常）：
       - 由 Service 层主动抛出
       - 包含 code、message、details 结构化信息
       - HTTP 状态码由 exc.status_code 决定
       - 常见场景：参数无效、业务规则冲突、资源不存在等
       
    2. KeyError（键错误 → 404）：
       - 通常发生在 registry.get(run_id) 时找不到对应实例
       - 自动转换为 RUN_NOT_FOUND 错误响应
       
    所有错误响应统一格式：
    ```json
    {
        "code": "ERROR_CODE",
        "message": "人类可读的错误描述",
        "details": {}  // 可选的附加信息
    }
    ```
    
    Args:
        app: FastAPI 应用实例（用于注册 exception_handler）
        
    Example:
        在 app.py 中调用：
        install_error_handlers(app)
        
        之后所有路由抛出的 ApiError 都会被自动捕获并格式化返回
    """
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        _ = request
        body = {"code": exc.code, "message": exc.message}
        if exc.details:
            body["details"] = exc.details
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(KeyError)
    async def handle_key_error(request: Request, exc: KeyError) -> JSONResponse:
        _ = request
        return JSONResponse(status_code=404, content={"code": "RUN_NOT_FOUND", "message": "run not found", "details": {"run_id": str(exc)}})
