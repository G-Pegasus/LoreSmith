from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from ainovel_py.domain.runtime_events import RuntimeQueueItem
from ainovel_py.store.io import IO


RUNTIME_QUEUE_PATH = "meta/runtime/queue.jsonl"
RUNTIME_CONTROL_PATH = "meta/runtime/control.json"


class RuntimeStore:
    """
    运行时队列存储管理器
    
    负责管理异步任务队列，支持任务的追加、查询和重置操作。
    使用 JSONL 格式存储队列数据，确保写入的原子性。
    
    队列项用于记录：
    - 待处理的写作任务
    - 重写请求
    - 评审任务
    - 其他异步操作
    """
    def __init__(self, io: IO) -> None:
        self.io = io
        self._seq_loaded = False
        self._next_seq = 0

    def append_queue(self, item: RuntimeQueueItem) -> RuntimeQueueItem:
        """
        追加队列项（带自动序列号分配）
        
        Args:
            item: 队列项
        
        Returns:
            带有序列号的队列项
        """
        def op() -> RuntimeQueueItem:
            self._ensure_seq_loaded_locked()
            self._next_seq += 1
            item.seq = self._next_seq
            if not item.time:
                item.time = datetime.utcnow()
            payload = asdict(item)
            payload["time"] = item.time.isoformat()
            self.io.append_line(RUNTIME_QUEUE_PATH, (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
            return item

        return self.io.with_write_lock(op)

    def load_queue(self) -> list[RuntimeQueueItem]:
        """加载完整的运行时队列"""
        try:
            data = self.io.read_file(RUNTIME_QUEUE_PATH).decode("utf-8")
        except FileNotFoundError:
            return []
        out: list[RuntimeQueueItem] = []
        for line in data.splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            out.append(
                RuntimeQueueItem(
                    seq=int(row.get("seq", 0) or 0),
                    time=datetime.fromisoformat(row.get("time")) if row.get("time") else datetime.utcnow(),
                    kind=str(row.get("kind", "") or ""),
                    priority=str(row.get("priority", "") or ""),
                    task_id=str(row.get("task_id", "") or ""),
                    agent=str(row.get("agent", "") or ""),
                    category=str(row.get("category", "") or ""),
                    summary=str(row.get("summary", "") or ""),
                    payload=row.get("payload"),
                )
            )
        return out

    def load_queue_after(self, after_seq: int) -> list[RuntimeQueueItem]:
        """加载指定序列号之后的队列项"""
        items = self.load_queue()
        if after_seq <= 0:
            return items
        return [x for x in items if x.seq > after_seq]

    def reset(self) -> None:
        """重置运行时状态（清空队列和任务目录）"""
        queue_file = self.io.path(RUNTIME_QUEUE_PATH)
        control_file = self.io.path(RUNTIME_CONTROL_PATH)
        tasks_dir = self.io.path("meta/runtime/tasks")
        if queue_file.exists():
            queue_file.unlink()
        if control_file.exists():
            control_file.unlink()
        if tasks_dir.exists():
            for p in tasks_dir.glob("**/*"):
                if p.is_file():
                    p.unlink()
        tasks_dir.mkdir(parents=True, exist_ok=True)
        self._seq_loaded = False
        self._next_seq = 0

    def _ensure_seq_loaded_locked(self) -> None:
        """确保序列号已加载（线程安全）"""
        if self._seq_loaded:
            return
        items = self.load_queue()
        self._next_seq = items[-1].seq if items else 0
        self._seq_loaded = True
