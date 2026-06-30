"""
运行时注册表模块 (Runtime Registry Module)

本模块实现了小说创作系统的运行时注册表，负责管理所有活跃的创作会话和任务。

核心组件：
1. RunSession: 创作会话数据模型，封装 Host 实例和运行状态
2. RunRegistry: 中央注册表，管理会话和任务的生命周期

主要职责：
- 会话管理：创建、查询、更新、删除创作会话
- 任务队列：管理待执行和正在执行的任务
- 线程安全：使用 RLock 保证多线程环境下的数据一致性
- 状态持久化：将会话和任务状态保存到存储，支持故障恢复
- 状态同步：实时同步会话和任务的状态标志

设计模式：
- 注册表模式（Registry Pattern）：集中管理所有运行时对象
- 仓储模式（Repository Pattern）：封装数据持久化逻辑
- 线程安全模式：使用锁保护共享资源

典型使用场景：
- API 层创建新会话时，通过 RunRegistry 注册
- Worker 从 RunRegistry 领取任务并执行
- 服务重启后，通过 restore() 恢复之前的运行状态
- 前端查询会话状态时，从 RunRegistry 获取最新数据
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock, Thread
from typing import Dict, Optional

from ainovel_py.bootstrap.config import Config, provider_config_from_dict, role_config_from_dict
from ainovel_py.host.host import Host
from ainovel_py.internal_api.persistence import RunRegistryStore, RunTaskStore
from ainovel_py.internal_api.tasks import RunTask


def utcnow() -> datetime:
    """
    获取当前 UTC 时间
    
    Returns:
        当前 UTC 时间的 datetime 对象
    """
    return datetime.now(timezone.utc)


@dataclass
class RunSession:
    """
    创作会话数据模型
    
    封装一次完整的小说创作会话的所有信息，包括配置、Host 实例、运行状态等。
    相当于一个"创作任务档案"，记录了从创建到完成的全过程。
    
    核心字段说明：
    
    标识字段：
    - run_id: 运行唯一标识（UUID），用于 API 查询和任务关联
    - story_id: 故事唯一标识，可能关联多个 run（如多次创作同一故事）
    
    配置字段：
    - output_dir: 输出目录路径，保存生成的小说文件
    - cfg: 配置对象，包含模型、风格、服务商等配置
    - host: Host 实例，负责协调创作流程的核心控制器
    
    时间字段：
    - created_at: 会话创建时间（UTC）
    - started_at: 会话开始执行时间（UTC）
    - finished_at: 会话完成时间（UTC，未完成时为 None）
    
    状态字段：
    - last_error_code: 最后一次错误代码（如 "INVALID_ARGUMENT"）
    - last_error_message: 最后一次错误消息
    - state_override: 状态覆盖标记（如 "failed"/"canceled"）
    - last_operation: 最后执行的操作（如 "create"/"start"/"pause"/"resume"）
    
    任务标志：
    - has_queued_task: 是否有待执行的任务（由 RunRegistry 自动同步）
    - has_running_task: 是否有正在执行的任务（由 RunRegistry 自动同步）
    
    线程控制：
    - worker: 执行此会话的 Worker 线程（用于监控和取消）
    - lock: 会话级别的可重入锁，保护会话内部状态的并发访问
    
    使用场景：
    - API 层创建新会话时，实例化 RunSession 并注册到 RunRegistry
    - Worker 执行任务时，从 RunRegistry 获取 RunSession 并访问其 host
    - 前端查询会话状态时，通过 RunRegistry.get(run_id) 获取 RunSession
    - 服务重启后，从持久化存储恢复 RunSession 对象
    
    线程安全说明：
    - RunSession 本身不是线程安全的
    - 访问会话内部状态时，应使用 session.lock 保护
    - 或者通过 RunRegistry 的线程安全方法间接访问
    
    Example:
        # 创建新会话
        session = RunSession(
            run_id="uuid-1234",
            story_id="story-001",
            output_dir="./output/novel",
            cfg=config,
            host=Host(config),
            last_operation="create"
        )
        
        # 检查会话是否忙碌
        if session.is_busy():
            print("会话正在执行任务")
        
        # 获取会话状态
        print(f"最后操作: {session.last_operation}")
        print(f"是否有待执行任务: {session.has_queued_task}")
    """
    
    # 标识字段
    run_id: str
    story_id: str
    
    # 配置字段
    output_dir: str
    cfg: Config
    host: Host
    
    # 时间字段
    created_at: datetime = field(default_factory=utcnow)
    started_at: datetime = field(default_factory=utcnow)
    finished_at: Optional[datetime] = None
    
    # 状态字段
    last_error_code: str = ""
    last_error_message: str = ""
    state_override: str = ""
    last_operation: str = ""
    
    # 线程控制
    worker: Optional[Thread] = None
    lock: RLock = field(default_factory=RLock)
    
    # 任务标志（由 RunRegistry 自动同步）
    has_queued_task: bool = False
    has_running_task: bool = False

    def is_busy(self) -> bool:
        """
        检查会话是否正在执行任务
        
        判断依据：
        - has_queued_task 为 True：有待执行的任务
        - has_running_task 为 True：有正在执行的任务
        
        Returns:
            True 表示会话忙碌（有待执行或正在执行的任务）
            False 表示会话空闲
            
        Note:
            此标志由 RunRegistry 自动同步，无需手动设置
            
        Example:
            if session.is_busy():
                print("会话正在执行任务，请稍后再试")
            else:
                print("会话空闲，可以执行新任务")
        """
        return self.has_queued_task or self.has_running_task


class RunRegistry:
    """
    运行时注册表（中央调度中心）
    
    管理所有活跃的创作会话和任务，相当于系统的"中央调度中心"。
    负责会话生命周期管理、任务队列调度、状态持久化和故障恢复。
    
    核心职责：
    
    1️⃣ 会话管理（Session Management）
       - 创建新会话：put(session)
       - 查询会话：get(run_id) / require(run_id)
       - 列出会话：list()
       - 持久化会话：persist(session)
       
    2️⃣ 任务管理（Task Management）
       - 添加任务：put_task(task)
       - 领取任务：claim_next_task()
       - 列出任务：list_tasks(run_id)
       - 持久化任务：persist_task(task)
       
    3️⃣ 状态同步（State Synchronization）
       - 实时同步会话的任务标志（has_queued_task, has_running_task）
       - 确保会话状态与任务队列状态一致
       
    4️⃣ 故障恢复（Disaster Recovery）
       - 从持久化存储恢复会话：restore()
       - 重建 Host 实例和配置对象
       - 重置运行中的任务为待执行状态
       
    5️⃣ 线程安全（Thread Safety）
       - 所有公共方法都使用 RLock 保护
       - 支持多 Worker 线程并发访问
       - 保证数据一致性
    
    数据结构：
    - _items: Dict[str, RunSession] - 会话字典 {run_id: RunSession}
    - _tasks: Dict[str, RunTask] - 任务字典 {task_id: RunTask}
    - _lock: RLock - 全局可重入锁，保护共享资源
    - _store: RunRegistryStore - 会话持久化存储（可选）
    - _task_store: RunTaskStore - 任务持久化存储（可选）
    
    线程安全保证：
    - 所有公共方法都使用 `with self._lock:` 保护
    - RLock 是可重入锁，允许同一线程多次获取
    - 避免并发修改导致的数据不一致
    
    持久化机制：
    - 每次修改会话或任务时，自动调用持久化方法
    - 如果 _store 为 None，则跳过持久化（内存模式）
    - 支持服务重启后恢复运行状态
    
    典型使用流程：
    
    场景1：创建新会话
    ```python
    session = RunSession(run_id="uuid-1234", ...)
    registry.put(session)  # 注册并持久化
    ```
    
    场景2：Worker 领取任务
    ```python
    task = registry.claim_next_task()  # 返回状态为 "queued" 的任务
    if task:
        session = registry.require(task.run_id)
        session.host.start(task.payload["prompt"])
    ```
    
    场景3：服务重启恢复
    ```python
    registry = RunRegistry(store=RunRegistryStore(), task_store=RunTaskStore())
    registry.restore()  # 从存储恢复所有会话和任务
    ```
    
    场景4：查询会话状态
    ```python
    session = registry.get(run_id)
    if session and session.is_busy():
        print("会话正在执行任务")
    ```
    
    设计模式：
    - 注册表模式（Registry Pattern）：集中管理所有运行时对象
    - 仓储模式（Repository Pattern）：封装数据持久化逻辑
    - 单例模式（Singleton Pattern）：通常全局只有一个 RunRegistry 实例
    
    性能考虑：
    - 使用字典存储会话和任务，查询时间复杂度 O(1)
    - 锁的粒度适中，避免过度竞争
    - 持久化操作在锁内执行，确保数据一致性
    
    注意事项：
    - 不要在持有锁的情况下执行耗时操作（如 LLM 调用）
    - 持久化存储失败不会影响内存中的数据
    - restore() 只在服务启动时调用一次
    """
    
    def __init__(self, store: RunRegistryStore | None = None, task_store: RunTaskStore | None = None) -> None:
        """
        初始化运行时注册表
        
        Args:
            store: 会话持久化存储（可选）
                   - None: 纯内存模式，服务重启后数据丢失
                   - RunRegistryStore: 持久化模式，支持故障恢复
            task_store: 任务持久化存储（可选）
                        - None: 纯内存模式
                        - RunTaskStore: 持久化模式
        
        Example:
            # 纯内存模式（测试环境）
            registry = RunRegistry()
            
            # 持久化模式（生产环境）
            store = RunRegistryStore("./data/sessions")
            task_store = RunTaskStore("./data/tasks")
            registry = RunRegistry(store=store, task_store=task_store)
            registry.restore()  # 恢复之前的会话
        """
        self._lock = RLock()  # 全局可重入锁，保护共享资源
        self._items: Dict[str, RunSession] = {}  # 会话字典 {run_id: RunSession}
        self._tasks: Dict[str, RunTask] = {}  # 任务字典 {task_id: RunTask}
        self._store = store  # 会话持久化存储（可选）
        self._task_store = task_store  # 任务持久化存储（可选）

    def get(self, run_id: str) -> Optional[RunSession]:
        """
        查询会话（可选返回）
        
        根据 run_id 查询对应的会话，如果不存在则返回 None。
        
        Args:
            run_id: 运行唯一标识
            
        Returns:
            RunSession 对象，如果不存在则返回 None
            
        Thread Safety:
            此方法是线程安全的，内部使用锁保护
            
        Example:
            session = registry.get("uuid-1234")
            if session:
                print(f"会话状态: {session.last_operation}")
            else:
                print("会话不存在")
        """
        with self._lock:
            return self._items.get(run_id)

    def put(self, session: RunSession) -> RunSession:
        """
        创建或更新会话
        
        将会话注册到注册表中，如果已存在则覆盖。
        同时会：
        1. 同步会话的任务标志（has_queued_task, has_running_task）
        2. 持久化会话到存储（如果 _store 不为 None）
        
        Args:
            session: 要注册的会话对象
            
        Returns:
            注册后的会话对象（与输入相同）
            
        Thread Safety:
            此方法是线程安全的，内部使用锁保护
            
        Example:
            session = RunSession(run_id="uuid-1234", ...)
            registry.put(session)  # 注册并持久化
        """
        with self._lock:
            self._items[session.run_id] = session
            self._sync_session_flags_locked(session.run_id)
            self._persist_locked(session)
            return session

    def require(self, run_id: str) -> RunSession:
        """
        查询会话（必须存在）
        
        根据 run_id 查询对应的会话，如果不存在则抛出 KeyError。
        适用于确定会话必须存在的场景（如 Worker 执行任务时）。
        
        Args:
            run_id: 运行唯一标识
            
        Returns:
            RunSession 对象
            
        Raises:
            KeyError: 如果 run_id 不存在
            
        Thread Safety:
            此方法是线程安全的，内部使用锁保护
            
        Example:
            try:
                session = registry.require("uuid-1234")
                session.host.start("写一本小说")
            except KeyError:
                print("会话不存在")
        """
        with self._lock:
            session = self._items.get(run_id)
            if session is None:
                raise KeyError(run_id)
            return session

    def persist(self, session: RunSession) -> None:
        """
        持久化会话
        
        将会话状态保存到持久化存储（如果 _store 不为 None）。
        同时会同步会话的任务标志。
        
        使用场景：
        - 会话状态发生变化时（如 last_operation 更新）
        - 需要确保状态持久化到存储
        
        Args:
            session: 要持久化的会话对象
            
        Thread Safety:
            此方法是线程安全的，内部使用锁保护
            
        Note:
            如果 _store 为 None，则此方法不执行任何操作
        """
        with self._lock:
            self._sync_session_flags_locked(session.run_id)
            self._persist_locked(session)

    def list(self) -> list[RunSession]:
        """
        列出所有会话
        
        返回注册表中所有活跃的会话列表。
        在返回前，会同步所有会话的任务标志。
        
        Returns:
            会话列表，按注册顺序排列
            
        Thread Safety:
            此方法是线程安全的，内部使用锁保护
            
        Example:
            sessions = registry.list()
            for session in sessions:
                print(f"会话 {session.run_id}: {session.last_operation}")
        """
        with self._lock:
            for run_id in self._items:
                self._sync_session_flags_locked(run_id)
            return list(self._items.values())

    def list_tasks(self, run_id: str = "") -> list[RunTask]:
        """
        列出任务
        
        返回任务列表，可以按 run_id 过滤。
        
        Args:
            run_id: 运行唯一标识（可选）
                    - 空字符串（默认）：返回所有任务
                    - 指定值：只返回该 run_id 的任务
            
        Returns:
            任务列表
            
        Thread Safety:
            此方法是线程安全的，内部使用锁保护
            
        Example:
            # 列出所有任务
            all_tasks = registry.list_tasks()
            
            # 列出指定会话的任务
            session_tasks = registry.list_tasks("uuid-1234")
        """
        with self._lock:
            items = list(self._tasks.values())
            if run_id:
                return [task for task in items if task.run_id == run_id]
            return items

    def put_task(self, task: RunTask) -> RunTask:
        """
        添加任务
        
        将任务添加到任务队列中，如果已存在则覆盖。
        同时会：
        1. 同步会话的任务标志
        2. 持久化任务到存储（如果 _task_store 不为 None）
        
        Args:
            task: 要添加的任务对象
            
        Returns:
            添加后的任务对象（与输入相同）
            
        Thread Safety:
            此方法是线程安全的，内部使用锁保护
            
        Example:
            task = RunTask(
                task_id="task-001",
                run_id="uuid-1234",
                op="start",
                payload={"prompt": "写一本仙侠小说"},
                status="queued"
            )
            registry.put_task(task)
        """
        with self._lock:
            self._tasks[task.task_id] = task
            self._sync_session_flags_locked(task.run_id)
            self._persist_task_locked(task)
            return task

    def persist_task(self, task: RunTask) -> None:
        """
        持久化任务
        
        将任务状态保存到持久化存储（如果 _task_store 不为 None）。
        同时会同步会话的任务标志。
        
        使用场景：
        - 任务状态发生变化时（如 status 从 "queued" 变为 "running"）
        - 需要确保任务状态持久化到存储
        
        Args:
            task: 要持久化的任务对象
            
        Thread Safety:
            此方法是线程安全的，内部使用锁保护
            
        Note:
            如果 _task_store 为 None，则此方法不执行任何操作
        """
        with self._lock:
            self._tasks[task.task_id] = task
            self._sync_session_flags_locked(task.run_id)
            self._persist_task_locked(task)

    def claim_next_task(self) -> Optional[RunTask]:
        """
        领取下一个待执行任务
        
        Worker 线程调用此方法从任务队列中领取下一个待执行的任务。
        
        工作流程：
        1. 按创建时间排序所有任务（FIFO 队列）
        2. 找到第一个状态为 "queued" 的任务
        3. 检查对应的会话是否存在
        4. 将任务状态改为 "running"
        5. 记录任务开始时间
        6. 同步会话的任务标志
        7. 持久化任务状态
        8. 返回任务
        
        Returns:
            RunTask 对象，如果没有待执行任务则返回 None
            
        Thread Safety:
            此方法是线程安全的，内部使用锁保护
            多个 Worker 同时调用时，只有一个能领取到任务
            
        Example:
            # Worker 线程循环领取任务
            while True:
                task = registry.claim_next_task()
                if task is None:
                    time.sleep(1)  # 没有任务，等待
                    continue
                
                session = registry.require(task.run_id)
                if task.op == "start":
                    session.host.start(task.payload["prompt"])
                elif task.op == "pause":
                    session.host.abort()
                
                # 任务完成，更新状态
                task.status = "completed"
                registry.persist_task(task)
        """
        with self._lock:
            for task in sorted(self._tasks.values(), key=lambda item: item.created_at):
                if task.status == "queued":
                    session = self._items.get(task.run_id)
                    if session is None:
                        continue
                    task.status = "running"
                    task.started_at = utcnow()
                    self._sync_session_flags_locked(task.run_id)
                    self._persist_task_locked(task)
                    return task
            return None

    def restore(self) -> None:
        """
        从持久化存储恢复会话和任务
        
        服务启动时调用此方法，从存储中恢复之前的运行状态。
        
        恢复流程：
        
        1️⃣ 恢复会话（Session Recovery）
           - 从 _store 加载所有会话数据
           - 重建 Config 对象（包括 providers 和 roles）
           - 调用 cfg.fill_defaults() 补全默认配置
           - 创建 Host 实例（会重新初始化协调器和工具）
           - 创建 RunSession 对象并注册到 _items
           
        2️⃣ 恢复任务（Task Recovery）
           - 从 _task_store 加载所有任务数据
           - 重建 RunTask 对象
           - 将状态为 "running" 的任务重置为 "queued"
             （因为服务重启了，之前的执行已中断，需要重新执行）
           - 注册到 _tasks
           
        3️⃣ 同步状态（State Synchronization）
           - 遍历所有会话，同步任务标志
           - 确保 has_queued_task 和 has_running_task 正确
        
        注意事项：
        - 此方法只在服务启动时调用一次
        - 如果 _store 或 _task_store 为 None，则跳过对应恢复
        - 恢复的 Host 实例是全新的，但配置和状态与之前一致
        - 运行中的任务会被重置为待执行状态，需要 Worker 重新领取
        
        Raises:
            各种异常：如果存储加载失败或对象重建失败
        
        Thread Safety:
            此方法应在服务启动时单线程调用，无需锁保护
            但内部调用的方法（如 _sync_session_flags_locked）需要锁
        
        Example:
            # 服务启动时
            store = RunRegistryStore("./data/sessions")
            task_store = RunTaskStore("./data/tasks")
            registry = RunRegistry(store=store, task_store=task_store)
            registry.restore()  # 恢复之前的会话和任务
            
            # Worker 可以继续领取任务
            task = registry.claim_next_task()
        """
        if self._store is not None:
            rows = self._store.load()
            for row in rows:
                cfg_raw = row.get("cfg") or {}
                providers_raw = cfg_raw.get("providers") or {}
                roles_raw = cfg_raw.get("roles") or {}
                cfg = Config(
                    output_dir=str(cfg_raw.get("output_dir", row.get("output_dir", "")) or row.get("output_dir", "")),
                    provider=str(cfg_raw.get("provider", "") or ""),
                    model=str(cfg_raw.get("model", "") or ""),
                    providers={name: provider_config_from_dict(data) for name, data in providers_raw.items()},
                    roles={name: role_config_from_dict(data) for name, data in roles_raw.items()},
                    style=str(cfg_raw.get("style", "default") or "default"),
                    context_window=int(cfg_raw.get("context_window", 128000) or 128000),
                )
                cfg.fill_defaults()
                if cfg.provider and cfg.provider not in cfg.providers:
                    from ainovel_py.bootstrap.config import ProviderConfig

                    cfg.providers[cfg.provider] = ProviderConfig(api_key="dummy-key")
                host = Host(cfg)
                session = RunSession(
                    run_id=str(row.get("run_id", "") or ""),
                    story_id=str(row.get("story_id", "") or ""),
                    output_dir=str(row.get("output_dir", cfg.output_dir) or cfg.output_dir),
                    cfg=cfg,
                    host=host,
                    last_error_code=str(row.get("last_error_code", "") or ""),
                    last_error_message=str(row.get("last_error_message", "") or ""),
                    state_override=str(row.get("state_override", "") or ""),
                    last_operation=str(row.get("last_operation", "") or ""),
                )
                self._items[session.run_id] = session
        if self._task_store is not None:
            for row in self._task_store.load():
                task = RunTask(
                    task_id=str(row.get("task_id", "") or ""),
                    run_id=str(row.get("run_id", "") or ""),
                    op=str(row.get("op", "") or ""),
                    payload=row.get("payload") if isinstance(row.get("payload"), dict) else {},
                    status=str(row.get("status", "queued") or "queued"),
                    error=str(row.get("error", "") or ""),
                )
                if task.status == "running":
                    task.status = "queued"
                self._tasks[task.task_id] = task
        for run_id in self._items:
            self._sync_session_flags_locked(run_id)

    def _persist_locked(self, session: RunSession) -> None:
        """
        持久化会话（内部方法，需要在锁内调用）
        
        将会话对象转换为存储格式并保存到持久化存储。
        
        工作流程：
        1. 检查 _store 是否为 None，如果是则直接返回
        2. 调用 _store.build_row(session) 将会话转换为字典行
        3. 调用 _store.upsert(row) 插入或更新存储
        
        Args:
            session: 要持久化的会话对象
            
        Note:
            此方法必须在持有 self._lock 的情况下调用
            方法名中的 "locked" 后缀表示调用者需要持有锁
            
        Performance:
            持久化操作是 I/O 密集型，可能较慢
            避免在持有锁的情况下执行大量持久化操作
        """
        if self._store is None:
            return
        self._store.upsert(self._store.build_row(session))

    def _persist_task_locked(self, task: RunTask) -> None:
        """
        持久化任务（内部方法，需要在锁内调用）
        
        将任务对象转换为存储格式并保存到持久化存储。
        
        工作流程：
        1. 检查 _task_store 是否为 None，如果是则直接返回
        2. 调用 _task_store.build_row(task) 将任务转换为字典行
        3. 调用 _task_store.upsert(row) 插入或更新存储
        
        Args:
            task: 要持久化的任务对象
            
        Note:
            此方法必须在持有 self._lock 的情况下调用
            方法名中的 "locked" 后缀表示调用者需要持有锁
            
        Performance:
            持久化操作是 I/O 密集型，可能较慢
            避免在持有锁的情况下执行大量持久化操作
        """
        if self._task_store is None:
            return
        self._task_store.upsert(self._task_store.build_row(task))

    def _sync_session_flags_locked(self, run_id: str) -> None:
        """
        同步会话的任务标志（内部方法，需要在锁内调用）
        
        根据任务队列的状态，更新会话的任务标志。
        确保会话的 has_queued_task 和 has_running_task 与实际任务状态一致。
        
        工作流程：
        1. 根据 run_id 获取会话对象
        2. 如果会话不存在，直接返回
        3. 遍历所有任务，统计该 run_id 的任务状态
        4. 更新会话的 has_queued_task 标志
        5. 更新会话的 has_running_task 标志
        
        Args:
            run_id: 要同步的会话 ID
            
        Note:
            此方法必须在持有 self._lock 的情况下调用
            方法名中的 "locked" 后缀表示调用者需要持有锁
            
        Example:
            # 添加任务后自动同步
            registry.put_task(task)  # 内部会调用 _sync_session_flags_locked
            
            # 查询会话时自动同步
            session = registry.get(run_id)  # 内部会调用 _sync_session_flags_locked
            
            # 检查会话状态
            if session.has_queued_task:
                print("有待执行的任务")
        """
        session = self._items.get(run_id)
        if session is None:
            return
        session.has_queued_task = any(task.run_id == run_id and task.status == "queued" for task in self._tasks.values())
        session.has_running_task = any(task.run_id == run_id and task.status == "running" for task in self._tasks.values())
