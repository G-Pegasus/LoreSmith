from __future__ import annotations

import os

from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ainovel_py.internal_api.service import RunService
from ainovel_py.internal_api.workspace_service import WorkspaceService

bearer = HTTPBearer(auto_error=False)


def get_run_service(request: Request) -> RunService:
    return request.app.state.run_service


def get_workspace_service(request: Request) -> WorkspaceService:
    return request.app.state.workspace_service


def require_internal_auth(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer)) -> None:
    expected = getattr(request.app.state, "settings", None)
    token = expected.token if expected is not None else os.environ.get("AINOVEL_INTERNAL_API_TOKEN", "").strip()
    expected = token.strip()
    if not expected:
        return
    actual = credentials.credentials if credentials is not None else ""
    if actual != expected:
        raise HTTPException(status_code=401, detail="unauthorized")
