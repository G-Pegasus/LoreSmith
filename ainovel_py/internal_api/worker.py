"""
后台工作线程管理器

本模块实现了任务队列的消费端，负责从注册表中领取任务并执行。
是整个"API 请求 → 异步执行"架构的核心桥梁。

工作原理（生产者-消费者模式）：
    ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
    │  API 路由     │     │  RunRegistry │     │ WorkerManager│
    │  (生产者)     │     │  (任务队列)   │     │  (消费者)     │
    ├──────────────┤     ├──────────────┤     ├──────────────┤
    │ create_run() │────→│ put_task()   │     │              │
    │ resume_run() │────→│ put_task()   │     │              │
    │              │     │              │────→│ claim_next() │──→ 执行
    │              │     │ claim_next() │←────│ _run() 循环  │
    └──────────────┘     └──────────────┘     └──────────────┘

线程模型：
    - WorkerManager 在独立的后台守护线程中运行
    - 主线程（FastAPI）负责接收请求、创建任务
    - 工作线程负责消费任务、调用 Host 执行创作
    - 两个线程通过 RunRegistry 的线程安全方法通信

支持的命令类型：
    - start:   启动新的创作流程
    - resume:  从断点恢复创作（可带或不带新提示）
    - continue: 追加内容继续创作
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

from ainovel_py.internal_api.registry import RunRegistry
from ainovel_py.internal_api.tasks import RunTask, utcnow


class WorkerManager:
    """
    后台工作线程管理器

    负责在独立线程中持续轮询任务队列，领取并执行创作任务。
    是"API 请求 → 异步执行"架构的核心组件。

    核心职责：
        1. 任务消费：从 RunRegistry 中领取待执行的任务
        2. 任务执行：根据任务类型调用 Host 的对应方法
        3. 状态更新：执行完成后更新任务和会话的状态
        4. 异常处理：捕获执行异常并记录错误信息

    生命周期：
        ┌─────────┐    start()    ┌─────────┐    stop()    ┌─────────┐
        │  未启动  │─────────────→│  运行中  │────────────→│  已停止  │
        └─────────┘              └─────────┘              └─────────┘

    线程安全：
        - 所有对 RunRegistry 的操作都通过其内部的 RLock 保护
        - _stop 事件使用 threading.Event，天然线程安全
        - 不需要额外的同步机制

    使用示例：
        # 在 app.py 中创建并启动
        registry = RunRegistry(store, task_store)
        worker = WorkerManager(registry)
        worker.start()  # 启动后台工作线程

        # 在服务关闭时停止
        worker.stop()   # 优雅停止工作线程
    """

    def __init__(self, registry: RunRegistry) -> None:
        """
        初始化工作线程管理器

        Args:
            registry: 运行注册表，用于领取任务和更新状态
                      通常是全局唯一的 RunRegistry 实例

        Note:
            初始化后不会自动启动工作线程，需要显式调用 start()
        """
        self.registry = registry
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """
        启动后台工作线程

        创建一个守护线程并启动，线程会持续轮询任务队列。
        如果线程已经在运行，则直接返回（幂等性保证）。

        线程配置：
            - daemon=True：守护线程，主线程退出时自动终止
              原因：工作线程不应阻止应用关闭
            - name="internal-api-worker"：便于日志和调试时识别

        线程安全：
            此方法不是线程安全的，应在应用启动时调用一次
            多次调用是安全的（有幂等性检查），但不推荐

        Example:
            worker = WorkerManager(registry)
            worker.start()  # 启动工作线程
            # 此时后台线程开始轮询任务队列
        """
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="internal-api-worker")
        self._thread.start()

    def stop(self) -> None:
        """
        优雅停止工作线程

        通过以下步骤安全地停止工作线程：
        1. 设置 _stop 事件标志，通知工作线程退出循环
        2. 等待工作线程结束（最多等待 2 秒）
        3. 如果超时，线程会因 daemon=True 随主线程一起退出

        注意：
            - stop() 后，正在执行的任务不会被中断
            - 工作线程会在当前任务执行完毕后检查 _stop 标志并退出
            - join(timeout=2) 给予 2 秒的宽限期

        Example:
            worker.stop()  # 通知工作线程停止
            # 最多等待 2 秒让当前任务完成
        """
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        """
        工作线程主循环

        持续轮询任务队列，领取并执行任务。
        当 _stop 事件被设置时退出循环。

        循环逻辑：
            ┌──────────────────────────────────┐
            │ while not _stop:                  │
            │   task = claim_next_task()        │
            │   if task:                        │
            │     _execute(task)  ←── 执行任务  │
            │   else:                           │
            │     sleep(0.1s)     ←── 空闲等待  │
            └──────────────────────────────────┘

        空闲等待策略：
            - 当没有任务时，sleep(0.1) 而不是忙等待
            - 0.1 秒的间隔在响应速度和 CPU 占用之间取得平衡
            - 太短（如 0.01s）：CPU 占用高
            - 太长（如 1s）：任务响应延迟大

        Note:
            此方法在守护线程中运行，不应直接调用
        """
        while not self._stop.is_set():
            task = self.registry.claim_next_task()
            if task is None:
                time.sleep(0.1)
                continue
            self._execute(task)

    def _execute(self, task: RunTask) -> None:
        """
        执行单个创作任务

        根据任务的操作类型（op），调用 Host 的对应方法执行创作。
        执行完成后更新任务和会话的状态。

        执行流程：
            ┌─────────────────────────────────────────────────────┐
            │ 1. 查找会话（session = registry.get(run_id)）       │
            │    └─ 不存在 → 标记任务失败，直接返回                 │
            ├─────────────────────────────────────────────────────┤
            │ 2. 更新任务状态为 "running"                          │
            │    └─ 记录 started_at 时间                          │
            ├─────────────────────────────────────────────────────┤
            │ 3. 根据 op 类型执行对应操作                          │
            │    ├─ "start"   → host.start_prepared(prompt)      │
            │    ├─ "resume"  → host.resume() / continue_run()   │
            │    └─ "continue" → host.continue_run(text)         │
            ├─────────────────────────────────────────────────────┤
            │ 4. 成功 → 清除错误状态，标记任务 "completed"         │
            │    失败 → 记录错误信息，标记任务 "failed"            │
            ├─────────────────────────────────────────────────────┤
            │ 5. finally: 更新完成时间，持久化状态                  │
            └─────────────────────────────────────────────────────┘

        操作类型详解：
            - "start": 启动新创作
                从 payload 中提取 prompt，调用 host.start_prepared()
                适用于首次启动创作流程

            - "resume": 恢复创作
                如果 payload 中有 prompt，调用 host.continue_run(prompt)
                如果没有 prompt，调用 host.resume()（从断点恢复）
                适用于暂停后恢复创作

            - "continue": 继续创作
                从 payload 中提取 text，调用 host.continue_run(text)
                适用于追加内容继续创作

        异常处理策略：
            - 捕获所有异常，防止工作线程崩溃
            - 如果会话未被取消（state_override != "canceled"）：
                · 记录错误码 "INTERNAL_ERROR"
                · 记录错误消息
                · 设置 state_override = "failed"
            - 如果会话已被取消：
                · 不覆盖取消状态
                · 任务仍标记为 "failed"

        取消状态保护：
            当用户在任务执行期间取消会话时：
            - state_override 被设为 "canceled"
            - 成功分支：不清除错误状态，不重置 state_override
            - 失败分支：不覆盖 "canceled" 为 "failed"
            - 确保 "取消" 状态不会被意外覆盖

        Args:
            task: 待执行的任务对象，包含操作类型和负载

        Note:
            此方法在守护线程中运行，不应直接调用
        """
        session = self.registry.get(task.run_id)
        if session is None:
            task.status = "failed"
            task.error = f"run not found: {task.run_id}"
            task.finished_at = utcnow()
            self.registry.persist_task(task)
            return

        task.status = "running"
        task.started_at = utcnow()
        self.registry.persist_task(task)
        session.last_operation = task.op
        self.registry.persist(session)

        try:
            if task.op == "start":
                prompt = str(task.payload.get("prompt", "") or "")
                session.host.start_prepared(prompt)
            elif task.op == "resume":
                prompt = str(task.payload.get("prompt", "") or "")
                if prompt:
                    session.host.continue_run(prompt)
                else:
                    session.host.resume()
            elif task.op == "continue":
                text = str(task.payload.get("text", "") or "")
                session.host.continue_run(text)
            else:
                raise ValueError(f"unknown task op: {task.op}")
            if session.state_override != "canceled":
                session.last_error_code = ""
                session.last_error_message = ""
                session.state_override = ""
            task.status = "completed"
        except Exception as exc:
            if session.state_override != "canceled":
                session.last_error_code = "INTERNAL_ERROR"
                session.last_error_message = str(exc)
                session.state_override = "failed"
            task.status = "failed"
            task.error = str(exc)
        finally:
            task.finished_at = utcnow()
            if session.host.lifecycle == "completed":
                session.finished_at = utcnow()
            self.registry.persist(session)
            self.registry.persist_task(task)
