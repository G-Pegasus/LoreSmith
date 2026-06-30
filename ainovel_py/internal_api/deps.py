from __future__ import annotations

import os

from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ainovel_py.internal_api.service import RunService
from ainovel_py.internal_api.workspace_service import WorkspaceService
# ------------------------------------------------------------------------------
# 1. 定义 Bearer Token 认证器
# 作用：自动解析请求头中的 Authorization: Bearer <token>
# auto_error=False 表示：没有 Token 不直接报错，交给我们自己处理
# ------------------------------------------------------------------------------
bearer = HTTPBearer(auto_error=False)


def get_run_service(request: Request) -> RunService:
    return request.app.state.run_service


def get_workspace_service(request: Request) -> WorkspaceService:
    return request.app.state.workspace_service

# ------------------------------------------------------------------------------
#  核心：内部接口 Token 鉴权方法
# 作用：所有内部 API 调用必须携带正确的 Token，否则返回 401
# 等价 Java：拦截器 Interceptor / Spring Security 认证
# ------------------------------------------------------------------------------
def require_internal_auth(
    request: Request,                          # 当前 HTTP 请求
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer)  # 解析出来的 Bearer Token
) -> None:
    # ----------------------
    # 步骤1：获取预期的正确 Token
    # ----------------------
    # 从应用全局配置中读取 settings
    expected = getattr(request.app.state, "settings", None)
    
    # 优先级1：从配置中取 Token
    # 优先级2：从环境变量 AINOVEL_INTERNAL_API_TOKEN 取 Token
    token = expected.token if expected is not None else os.environ.get("AINOVEL_INTERNAL_API_TOKEN", "").strip()
    
    # 清理空格，保证比对准确
    expected_token = token.strip()

    # ----------------------
    # 步骤2：如果没有配置 Token → 不做鉴权（直接放行）
    # ----------------------
    if not expected_token:
        return

    # ----------------------
    # 步骤3：获取请求中携带的真实 Token
    # ----------------------
    actual_token = credentials.credentials if credentials is not None else ""

    # ----------------------
    # 步骤4：Token 不匹配 → 直接抛出 401 未授权
    # ----------------------
    if actual_token != expected_token:
        raise HTTPException(status_code=401, detail="unauthorized")
