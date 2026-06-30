from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from ainovel_py.internal_api.deps import get_workspace_service, require_internal_auth
from ainovel_py.internal_api.mappers import envelope
from ainovel_py.internal_api.response_dto import Envelope, ErrorResponse, WorkspaceReferenceDetailPayload, WorkspaceReferenceSnapshotPayload
from ainovel_py.internal_api.workspace_dto import WorkspaceAssistantThreadUpdateRequest, WorkspaceIntentPayload, WorkspaceIntentRequest, WorkspaceNodeMutationRequest, WorkspaceNodeUpdateRequest, WorkspaceRunBridgeUpdateRequest, WorkspaceSnapshotPayload
from ainovel_py.internal_api.workspace_service import WorkspaceService

router = APIRouter(prefix="/internal/v1", dependencies=[Depends(require_internal_auth)])


@router.get("/workspace", response_model=Envelope[WorkspaceSnapshotPayload], responses={401: {"model": ErrorResponse}})
async def workspace_snapshot(story_id: str = Query(min_length=1), service: WorkspaceService = Depends(get_workspace_service)) -> dict[str, object]:
    return envelope(service.get_workspace_snapshot(story_id))


@router.post("/workspace/nodes", response_model=Envelope[WorkspaceSnapshotPayload], responses={401: {"model": ErrorResponse}})
async def workspace_create_node(req: WorkspaceNodeMutationRequest, story_id: str = Query(min_length=1), service: WorkspaceService = Depends(get_workspace_service)) -> dict[str, object]:
    return envelope(service.create_workspace_node(story_id, req))


@router.put("/workspace/nodes/{node_id}", response_model=Envelope[WorkspaceSnapshotPayload], responses={401: {"model": ErrorResponse}})
async def workspace_update_node(node_id: str, req: WorkspaceNodeUpdateRequest, story_id: str = Query(min_length=1), service: WorkspaceService = Depends(get_workspace_service)) -> dict[str, object]:
    return envelope(service.update_workspace_node(story_id, node_id, req))


@router.put("/workspace/run-bridge", response_model=Envelope[WorkspaceSnapshotPayload], responses={401: {"model": ErrorResponse}})
async def workspace_run_bridge_update(req: WorkspaceRunBridgeUpdateRequest, story_id: str = Query(min_length=1), service: WorkspaceService = Depends(get_workspace_service)) -> dict[str, object]:
    return envelope(service.update_workspace_run_bridge(story_id, req))


@router.put("/workspace/assistant-thread", response_model=Envelope[WorkspaceSnapshotPayload], responses={401: {"model": ErrorResponse}})
async def workspace_assistant_thread_update(req: WorkspaceAssistantThreadUpdateRequest, story_id: str = Query(min_length=1), service: WorkspaceService = Depends(get_workspace_service)) -> dict[str, object]:
    return envelope(service.update_workspace_assistant_thread(story_id, req))


@router.get("/workspace/reference-snapshot", response_model=Envelope[WorkspaceReferenceSnapshotPayload], responses={401: {"model": ErrorResponse}})
async def workspace_reference_snapshot(story_id: str = Query(min_length=1), service: WorkspaceService = Depends(get_workspace_service)) -> dict[str, object]:
    return envelope(service.get_workspace_reference_snapshot(story_id))


@router.put("/workspace/reference-snapshot", response_model=Envelope[WorkspaceReferenceSnapshotPayload], responses={401: {"model": ErrorResponse}})
async def workspace_reference_snapshot_update(story_id: str = Query(min_length=1), payload: dict[str, object] = None, service: WorkspaceService = Depends(get_workspace_service)) -> dict[str, object]:
    return envelope(service.save_workspace_reference_snapshot(story_id, payload or {}))


@router.get("/workspace/reference-detail", response_model=Envelope[WorkspaceReferenceDetailPayload], responses={401: {"model": ErrorResponse}})
async def workspace_reference_detail(story_id: str = Query(min_length=1), service: WorkspaceService = Depends(get_workspace_service)) -> dict[str, object]:
    return envelope(service.get_workspace_reference_detail(story_id))


@router.post("/workspace/intent", response_model=Envelope[WorkspaceIntentPayload], responses={401: {"model": ErrorResponse}})
async def workspace_intent(req: WorkspaceIntentRequest, service: WorkspaceService = Depends(get_workspace_service)) -> dict[str, object]:
    return envelope(service.handle_workspace_intent(req))


@router.post("/workspace/intent/stream", responses={401: {"model": ErrorResponse}})
async def workspace_intent_stream(req: WorkspaceIntentRequest, service: WorkspaceService = Depends(get_workspace_service)) -> StreamingResponse:
    return StreamingResponse(service.stream_workspace_intent(req), media_type="text/event-stream")
