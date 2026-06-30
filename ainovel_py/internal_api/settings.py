from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass  # Python 注解：自动生成构造方法、toString、equals 等
class InternalApiSettings:
    # API 服务启动的 IP（默认本地 127.0.0.1）
    host: str = "127.0.0.1"
    # API 服务启动的端口（默认 8000）
    port: int = 8000
    # 内部接口认证 Token（用于接口安全校验，就是你上一段代码里的鉴权）
    token: str = ""
    # 运行记录持久化文件路径（等价数据库文件，保存任务运行状态）
    registry_path: str = str(Path("output") / "internal_api" / "runs.json")
# -----------------------------------------------------------------------------
# 加载配置的方法：从【环境变量】读取配置，没有则用【默认值】
# 等价 Java：
# public class InternalApiSettingsLoader {
#     public static InternalApiSettings loadSettings() { ... }
# }
# -----------------------------------------------------------------------------
def load_settings() -> InternalApiSettings:
    # --------------------------
    # 1. 读取 HOST
    # 优先级：环境变量 AINOVEL_INTERNAL_API_HOST → 没有就用 127.0.0.1
    # --------------------------
    host = os.environ.get("AINOVEL_INTERNAL_API_HOST", "127.0.0.1").strip() or "127.0.0.1"
    # --------------------------
    # 2. 读取 PORT（转成 int）
    # 优先级：环境变量 AINOVEL_INTERNAL_API_PORT → 没有就用 8000
    # --------------------------
    port_raw = os.environ.get("AINOVEL_INTERNAL_API_PORT", "8000").strip() or "8000"
    # --------------------------
    # 3. 读取 API 认证 TOKEN
    # 优先级：环境变量 AINOVEL_INTERNAL_API_TOKEN → 没有则为空字符串
    # --------------------------
    token = os.environ.get("AINOVEL_INTERNAL_API_TOKEN", "").strip()
    # --------------------------
    # 4. 读取持久化文件路径
    # 优先级：环境变量 AINOVEL_INTERNAL_API_REGISTRY → 没有则用默认路径
    # 默认路径：output/internal_api/runs.json
    # --------------------------
    registry_path = os.environ.get("AINOVEL_INTERNAL_API_REGISTRY", "").strip() or str(Path("output") / "internal_api" / "runs.json")
    # --------------------------
    # 5. 端口号容错处理：转成 int，失败则默认 8000
    # --------------------------
    try:
        port = int(port_raw)
    except ValueError:
        port = 8000

    # --------------------------
    # 6. 构造配置对象并返回
    # --------------------------
    return InternalApiSettings(
        host=host,
        port=port,
        token=token,
        registry_path=registry_path
    )