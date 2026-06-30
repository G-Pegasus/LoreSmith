"""
持久化存储模块

本模块负责将运行会话（RunSession）和任务（RunTask）的数据持久化到 JSON 文件中，
实现服务重启后的状态恢复。

核心功能：
    - RunRegistryStore：会话存储，管理 runs.json 文件
    - RunTaskStore：任务存储，管理 runs.json.tasks 文件

存储架构：
    ┌─────────────────────────────────────────────────────────────┐
    │                      文件系统                               │
    │  ┌─────────────────┐    ┌─────────────────────┐           │
    │  │  runs.json       │    │  runs.json.tasks    │           │
    │  │  [              ]│    │  [                  ]│           │
    │  │   {run_id, ...}, │    │   {task_id, ...},   │           │
    │  │   {run_id, ...}  │    │   {task_id, ...}    │           │
    │  │  ]              │    │  ]                   │           │
    │  └─────────────────┘    └─────────────────────┘           │
    └─────────────────────────────────────────────────────────────┘

数据流：
    ┌──────────┐   build_row()   ┌──────────────────┐   upsert()   ┌────────────┐
    │ RunSession│───────────────→│ Dict[str, Any]   │────────────→│ JSON 文件   │
    │ RunTask   │   (序列化)      │ (字典行)          │  (写入文件)  │            │
    └──────────┘                 └──────────────────┘              └────────────┘

    ┌────────────┐   load()      ┌──────────────────┐  restore()  ┌──────────┐
    │ JSON 文件   │─────────────→│ List[Dict]       │────────────→│ RunSession│
    │            │  (读取文件)    │ (字典行列表)      │  (反序列化)  │ RunTask   │
    └────────────┘               └──────────────────┘             └──────────┘

设计说明：
    - 使用 JSON 文件而非数据库，因为数据量小、结构简单
    - upsert 语义：存在则更新，不存在则新增
    - 每次写入都是全量覆盖（load → 修改 → save），适合小数据量场景
    - 线程安全由上层 RunRegistry 的 RLock 保证

等价 Java 组件：
    - RunRegistryStore ≈ RunSessionRepository
    - RunTaskStore ≈ RunTaskRepository
    - IO ≈ FileUtil / JsonFileUtil
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from ainovel_py.internal_api.tasks import RunTask
from ainovel_py.store.io import IO


def _iso_or_empty(value: Optional[datetime]) -> str:
    """
    将 datetime 对象转换为 ISO 8601 格式字符串

    如果值为 None，返回空字符串而非 "None"，
    避免 JSON 中出现无效的字符串 "None"。

    Args:
        value: 可选的 datetime 对象

    Returns:
        ISO 格式字符串（如 "2024-01-15T10:30:00+00:00"）或空字符串

    Example:
        >>> _iso_or_empty(datetime(2024, 1, 15, 10, 30))
        '2024-01-15T10:30:00'
        >>> _iso_or_empty(None)
        ''
    """
    return value.isoformat() if value is not None else ""


class RunRegistryStore:
    """
    运行会话持久化存储

    负责将 RunSession 的数据序列化为字典，并持久化到 JSON 文件中。
    支持加载全部记录、保存全部记录、以及按 run_id 进行 upsert 操作。

    存储文件格式（runs.json）：
        [
            {
                "run_id": "uuid-1234",
                "story_id": "story-001",
                "output_dir": "./output/story-001",
                "created_at": "2024-01-15T10:30:00+00:00",
                "started_at": "2024-01-15T10:30:05+00:00",
                "finished_at": "",
                "last_error_code": "",
                "last_error_message": "",
                "state_override": "",
                "last_operation": "start",
                "cfg": {
                    "output_dir": "./output/story-001",
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "providers": {"deepseek": {"api_key": "sk-xxx", ...}},
                    "roles": {"coordinator": {"provider": "deepseek", ...}},
                    "style": "xianxia",
                    "context_window": 128000
                }
            }
        ]

    线程安全：
        本类不保证线程安全，由上层 RunRegistry 的 RLock 保护

    使用场景：
        - 服务启动时：调用 load() 恢复之前的运行会话
        - 创建/更新会话时：调用 upsert() 持久化会话状态
        - 服务重启后：通过 restore() 重建 RunSession 对象
    """

    def __init__(self, path: str) -> None:
        """
        初始化会话存储

        Args:
            path: JSON 文件路径，如 "./data/runs.json"
                  文件不存在时会自动创建（首次 save 时）
        """
        self.io = IO(".")
        self.path = path

    def load(self) -> List[Dict[str, Any]]:
        """
        从 JSON 文件加载所有会话记录

        读取指定路径的 JSON 文件，返回字典列表。
        如果文件不存在或格式不正确，返回空列表。

        Returns:
            会话字典列表，每条记录包含 run_id、cfg 等字段

        Note:
            - 文件不存在时返回 []，不抛异常
            - 文件内容不是列表时也返回 []（容错处理）
        """
        try:
            data = self.io.read_json(self.path)
        except FileNotFoundError:
            return []
        return data if isinstance(data, list) else []

    def save(self, rows: List[Dict[str, Any]]) -> None:
        """
        将所有会话记录保存到 JSON 文件

        全量覆盖写入，不是增量追加。

        Args:
            rows: 要保存的会话字典列表

        Note:
            此操作是全量覆盖，会替换文件中的所有内容
            通常在 upsert() 内部调用，不直接使用
        """
        self.io.write_json(self.path, rows)

    def upsert(self, row: Dict[str, Any]) -> None:
        """
        新增或更新一条会话记录

        根据 run_id 判断是更新还是新增：
        - 如果找到相同 run_id 的记录，替换它（更新）
        - 如果没有找到，追加到列表末尾（新增）

        工作流程：
            1. load() 读取全部记录
            2. 遍历查找匹配的 run_id
            3. 找到 → 替换该条记录
            4. 未找到 → 追加新记录
            5. save() 全量写回文件

        Args:
            row: 要新增或更新的会话字典，必须包含 "run_id" 字段

        Note:
            - 每次操作都会读写整个文件，适合小数据量场景
            - 大数据量场景应考虑使用数据库
        """
        rows = self.load()
        replaced = False
        for idx, existing in enumerate(rows):
            if str(existing.get("run_id", "")) == str(row.get("run_id", "")):
                rows[idx] = row
                replaced = True
                break
        if not replaced:
            rows.append(row)
        self.save(rows)

    @staticmethod
    def build_row(session) -> Dict[str, Any]:
        """
        将 RunSession 对象序列化为可存储的字典

        将内存中的 RunSession 对象转换为纯字典结构，
        便于 JSON 序列化和持久化存储。

        序列化规则：
            - datetime → ISO 8601 字符串（通过 _iso_or_empty）
            - Config 对象 → 嵌套字典
            - ProviderConfig / RoleConfig → 通过 asdict() 转换
            - 简单字段（str, int）→ 直接保留

        Args:
            session: RunSession 对象，包含 cfg、host 等属性

        Returns:
            可 JSON 序列化的字典，结构如下：
            {
                "run_id": str,
                "story_id": str,
                "output_dir": str,
                "created_at": str,       # ISO 格式
                "started_at": str,       # ISO 格式
                "finished_at": str,      # ISO 格式
                "last_error_code": str,
                "last_error_message": str,
                "state_override": str,
                "last_operation": str,
                "cfg": {
                    "output_dir": str,
                    "provider": str,
                    "model": str,
                    "providers": {name: dict, ...},
                    "roles": {name: dict, ...},
                    "style": str,
                    "context_window": int
                }
            }

        Note:
            - Host 对象不参与序列化（运行时重建）
            - 反序列化在 RunRegistry.restore() 中完成
        """
        return {
            "run_id": session.run_id,
            "story_id": session.story_id,
            "output_dir": session.output_dir,
            "created_at": _iso_or_empty(session.created_at),
            "started_at": _iso_or_empty(session.started_at),
            "finished_at": _iso_or_empty(session.finished_at),
            "last_error_code": session.last_error_code,
            "last_error_message": session.last_error_message,
            "state_override": session.state_override,
            "last_operation": session.last_operation,
            "cfg": {
                "output_dir": session.cfg.output_dir,
                "provider": session.cfg.provider,
                "model": session.cfg.model,
                "providers": {
                    name: asdict(pc) for name, pc in session.cfg.providers.items()
                },
                "roles": {
                    name: asdict(rc) for name, rc in session.cfg.roles.items()
                },
                "style": session.cfg.style,
                "context_window": session.cfg.context_window,
            },
        }


class RunTaskStore:
    """
    任务持久化存储

    负责将 RunTask 的数据序列化为字典，并持久化到 JSON 文件中。
    结构和逻辑与 RunRegistryStore 类似，但存储的是任务数据。

    存储文件格式（runs.json.tasks）：
        [
            {
                "task_id": "task-uuid-001",
                "run_id": "run-uuid-1234",
                "op": "start",
                "payload": {"prompt": "写一本仙侠小说"},
                "status": "completed",
                "created_at": "2024-01-15T10:30:00+00:00",
                "started_at": "2024-01-15T10:30:01+00:00",
                "finished_at": "2024-01-15T10:35:00+00:00",
                "error": ""
            }
        ]

    与 RunRegistryStore 的区别：
        - 按 task_id（而非 run_id）进行 upsert
        - 存储任务操作（op）和负载（payload）
        - 记录任务的执行状态和错误信息

    线程安全：
        本类不保证线程安全，由上层 RunRegistry 的 RLock 保护
    """

    def __init__(self, path: str) -> None:
        """
        初始化任务存储

        Args:
            path: JSON 文件路径，如 "./data/runs.json.tasks"
                  文件不存在时会自动创建（首次 save 时）
        """
        self.io = IO(".")
        self.path = path

    def load(self) -> List[Dict[str, Any]]:
        """
        从 JSON 文件加载所有任务记录

        Returns:
            任务字典列表，每条记录包含 task_id、op、status 等字段

        Note:
            - 文件不存在时返回 []，不抛异常
            - 文件内容不是列表时也返回 []（容错处理）
        """
        try:
            data = self.io.read_json(self.path)
        except FileNotFoundError:
            return []
        return data if isinstance(data, list) else []

    def save(self, rows: List[Dict[str, Any]]) -> None:
        """
        将所有任务记录保存到 JSON 文件

        全量覆盖写入，不是增量追加。

        Args:
            rows: 要保存的任务字典列表
        """
        self.io.write_json(self.path, rows)

    def upsert(self, row: Dict[str, Any]) -> None:
        """
        新增或更新一条任务记录

        根据 task_id 判断是更新还是新增：
        - 如果找到相同 task_id 的记录，替换它（更新）
        - 如果没有找到，追加到列表末尾（新增）

        Args:
            row: 要新增或更新的任务字典，必须包含 "task_id" 字段
        """
        rows = self.load()
        replaced = False
        for idx, existing in enumerate(rows):
            if str(existing.get("task_id", "")) == str(row.get("task_id", "")):
                rows[idx] = row
                replaced = True
                break
        if not replaced:
            rows.append(row)
        self.save(rows)

    @staticmethod
    def build_row(task: RunTask) -> Dict[str, Any]:
        """
        将 RunTask 对象序列化为可存储的字典

        Args:
            task: RunTask 对象，包含 task_id、op、payload 等属性

        Returns:
            可 JSON 序列化的字典，结构如下：
            {
                "task_id": str,          # 任务唯一标识
                "run_id": str,           # 关联的运行会话ID
                "op": str,               # 操作类型（start/resume/continue）
                "payload": dict,         # 任务参数（如 prompt）
                "status": str,           # 任务状态（queued/running/completed/failed）
                "created_at": str,       # ISO 格式
                "started_at": str,       # ISO 格式
                "finished_at": str,      # ISO 格式
                "error": str             # 错误信息
            }
        """
        return {
            "task_id": task.task_id,
            "run_id": task.run_id,
            "op": task.op,
            "payload": task.payload,
            "status": task.status,
            "created_at": _iso_or_empty(task.created_at),
            "started_at": _iso_or_empty(task.started_at),
            "finished_at": _iso_or_empty(task.finished_at),
            "error": task.error,
        }
