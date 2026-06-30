from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime

from ainovel_py.domain.checkpoint import Checkpoint, Scope
from ainovel_py.store.io import IO


CHECKPOINTS_FILE = "meta/checkpoints.jsonl"


class CheckpointStore:
    """
    检查点存储管理器
    
    负责管理创作过程中的检查点记录，支持断点续传功能。
    使用 JSONL 格式存储，按顺序追加写入。
    
    检查点用于记录：
    - 章节写作进度
    - 卷/篇章摘要生成
    - 各种处理步骤的完成状态
    """
    def __init__(self, io: IO) -> None:
        self.io = io
        self._next_seq = 0
        self._load_seq()

    def _load_seq(self) -> None:
        """加载最新序列号"""
        all_items = self.all()
        self._next_seq = all_items[-1].seq if all_items else 0

    def append(self, scope: Scope, step: str, artifact: str = "", digest: str = "") -> Checkpoint:
        """
        追加检查点（带去重逻辑）
        
        Args:
            scope: 作用域（章节/卷/篇章）
            step: 步骤名称
            artifact: 关联产物路径
            digest: 产物摘要（用于去重）
        
        Returns:
            创建的检查点（如果已存在相同的则返回已有的）
        """
        def op() -> Checkpoint:
            if digest:
                for cp in reversed(self._load_all_unlocked()):
                    if cp.scope.matches(scope) and cp.step == step and cp.digest == digest:
                        return cp
            self._next_seq += 1
            cp = Checkpoint(
                seq=self._next_seq,
                scope=scope,
                step=step,
                artifact=artifact,
                digest=digest,
                occurred_at=datetime.utcnow(),
            )
            payload = asdict(cp)
            payload["occurred_at"] = cp.occurred_at.isoformat()
            payload["scope"] = asdict(cp.scope)
            self.io.append_line(CHECKPOINTS_FILE, (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
            return cp

        return self.io.with_write_lock(op)

    def latest(self, scope: Scope) -> Checkpoint | None:
        """获取指定作用域的最新检查点"""
        for cp in reversed(self.all()):
            if cp.scope.matches(scope):
                return cp
        return None

    def latest_by_step(self, scope: Scope, step: str) -> Checkpoint | None:
        """获取指定作用域和步骤的最新检查点"""
        for cp in reversed(self.all()):
            if cp.scope.matches(scope) and cp.step == step:
                return cp
        return None

    def latest_global(self) -> Checkpoint | None:
        """获取全局最新检查点"""
        items = self.all()
        return items[-1] if items else None

    def all(self) -> list[Checkpoint]:
        """获取所有检查点"""
        return self._load_all_unlocked()

    def reset(self) -> None:
        """重置所有检查点"""
        self.io.remove_file(CHECKPOINTS_FILE)
        self._next_seq = 0

    def _load_all_unlocked(self) -> list[Checkpoint]:
        """非线程安全版本的加载所有检查点"""
        try:
            raw = self.io.read_file(CHECKPOINTS_FILE).decode("utf-8")
        except FileNotFoundError:
            return []
        items: list[Checkpoint] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                scope_raw = row.get("scope") or {}
                scope = Scope(
                    kind=str(scope_raw.get("kind", "") or ""),
                    chapter=int(scope_raw.get("chapter", 0) or 0),
                    volume=int(scope_raw.get("volume", 0) or 0),
                    arc=int(scope_raw.get("arc", 0) or 0),
                )
                items.append(
                    Checkpoint(
                        seq=int(row.get("seq", 0) or 0),
                        scope=scope,
                        step=str(row.get("step", "") or ""),
                        artifact=str(row.get("artifact", "") or ""),
                        digest=str(row.get("digest", "") or ""),
                        occurred_at=datetime.fromisoformat(row.get("occurred_at")) if row.get("occurred_at") else datetime.utcnow(),
                    )
                )
            except Exception:
                continue
        return items
