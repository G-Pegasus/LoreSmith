from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Callable


class IO:
    """
    文件 IO 工具类
    
    提供线程安全的文件读写操作，支持：
    - 原子写入（通过临时文件 + rename）
    - JSON 序列化/反序列化
    - Markdown 文件写入
    - 行追加操作
    
    使用 RLock 保证线程安全，支持嵌套锁定。
    """
    def __init__(self, directory: str) -> None:
        self.dir = Path(directory)
        self._mu = threading.RLock()

    def path(self, rel: str) -> Path:
        """获取相对路径对应的绝对路径"""
        return self.dir / rel

    def read_file(self, rel: str) -> bytes:
        """线程安全地读取文件内容"""
        with self._mu:
            return self.read_file_unlocked(rel)

    def read_file_unlocked(self, rel: str) -> bytes:
        """非线程安全版本的文件读取"""
        return self.path(rel).read_bytes()

    def write_file_unlocked(self, rel: str, data: bytes) -> None:
        """
        原子写入文件
        
        使用临时文件 + os.replace 保证写入的原子性，防止中途崩溃导致文件损坏。
        """
        p = self.path(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.parent / f"{p.name}.tmp-{os.getpid()}"
        with tmp.open("wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)

    def read_json(self, rel: str) -> Any:
        """线程安全地读取 JSON 文件"""
        with self._mu:
            return self.read_json_unlocked(rel)

    def read_json_unlocked(self, rel: str) -> Any:
        """非线程安全版本的 JSON 读取"""
        return json.loads(self.read_file_unlocked(rel).decode("utf-8"))

    def write_json(self, rel: str, value: Any) -> None:
        """线程安全地写入 JSON 文件"""
        with self._mu:
            self.write_json_unlocked(rel, value)

    def write_json_unlocked(self, rel: str, value: Any) -> None:
        """非线程安全版本的 JSON 写入"""
        data = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
        self.write_file_unlocked(rel, data)

    def write_markdown(self, rel: str, content: str) -> None:
        """线程安全地写入 Markdown 文件"""
        with self._mu:
            self.write_file_unlocked(rel, content.encode("utf-8"))

    def append_line(self, rel: str, data: bytes) -> None:
        """线程安全地追加一行数据到文件"""
        with self._mu:
            p = self.path(rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("ab") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())

    def remove_file(self, rel: str) -> None:
        """线程安全地删除文件（忽略不存在的文件）"""
        with self._mu:
            p = self.path(rel)
            try:
                p.unlink()
            except FileNotFoundError:
                pass

    def with_write_lock(self, fn: Callable[[], Any]) -> Any:
        """在写锁保护下执行函数"""
        with self._mu:
            return fn()

    def ensure_dirs(self, dirs: list[str]) -> None:
        """确保指定目录存在"""
        for d in dirs:
            (self.dir / d).mkdir(parents=True, exist_ok=True)
