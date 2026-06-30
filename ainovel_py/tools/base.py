from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class Tool(Protocol):
    """
    工具协议接口
    
    定义工具必须实现的方法：
    - name(): 返回工具名称
    - execute(args): 执行工具逻辑并返回结果
    """
    def name(self) -> str: ...
    def execute(self, args: dict[str, Any]) -> dict[str, Any]: ...


@dataclass
class ToolError(Exception):
    """
    工具执行异常
    
    用于封装工具执行过程中的错误。
    """
    message: str

    def __str__(self) -> str:
        return self.message
