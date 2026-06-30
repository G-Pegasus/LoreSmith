from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ainovel_py.internal_api.deps import get_run_service, require_internal_auth
from ainovel_py.internal_api.dto import CreateRunRequest, InstructionRequest, PauseRunRequest, ResumeRunRequest
from ainovel_py.internal_api.errors import ApiError
from ainovel_py.internal_api.mappers import envelope, map_artifacts, map_chapter, map_create_run, map_event, map_events, map_instruction_ack, map_pause_ack, map_run
from ainovel_py.internal_api.response_dto import AckPayload, ArtifactListPayload, ChapterPayload, CreateRunPayload, Envelope, ErrorResponse, EventsPagePayload, HealthPayload, RunListPayload, RunPayload
from ainovel_py.internal_api.service import RunService

router = APIRouter(prefix="/internal/v1", dependencies=[Depends(require_internal_auth)])


def _format_sse_event(item: dict[str, object]) -> str:
    event_type = str(item.get("type", "ui.event") or "ui.event")
    import json
    return f"event: {event_type}\ndata: {json.dumps(item, ensure_ascii=False)}\n\n"


@router.post("/runs", response_model=Envelope[CreateRunPayload], responses={401: {"model": ErrorResponse}, 409: {"model": ErrorResponse}})
async def create_run(req: CreateRunRequest, service: RunService = Depends(get_run_service)) -> dict[str, object]:
    session = service.create_run(req)
    report = session.host.report()
    return envelope(map_create_run(session, report))


@router.get("/health", response_model=Envelope[HealthPayload], responses={401: {"model": ErrorResponse}})
async def health(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    registry = request.app.state.run_registry
    return envelope({
        "status": "ok",
        "host": settings.host,
        "port": settings.port,
        "run_count": len(registry.list()),
    })


@router.get("/runs", response_model=Envelope[RunListPayload], responses={401: {"model": ErrorResponse}})
async def list_runs(
    status: str = Query(default=""),
    story_id: str = Query(default=""),
    service: RunService = Depends(get_run_service),
) -> dict[str, object]:
    items = [map_run(session, report) for session, report in service.list_runs(status=status, story_id=story_id)]
    return envelope({"items": items})


@router.get("/runs/{run_id}", response_model=Envelope[RunPayload], responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}})
async def get_run(run_id: str, service: RunService = Depends(get_run_service)) -> dict[str, object]:
    session, report = service.get_report(run_id)
    return envelope(map_run(session, report))


@router.post("/runs/{run_id}/pause", response_model=Envelope[AckPayload], responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}})
async def pause_run(run_id: str, req: PauseRunRequest, service: RunService = Depends(get_run_service)) -> dict[str, object]:
    _ = req
    session = service.pause_run(run_id)
    return envelope(map_pause_ack(session, session.host.report()))


@router.post("/runs/{run_id}/resume", response_model=Envelope[AckPayload], responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}})
async def resume_run(run_id: str, req: ResumeRunRequest, service: RunService = Depends(get_run_service)) -> dict[str, object]:
    session = service.resume_run(run_id, req)
    return envelope(map_pause_ack(session, session.host.report()))


@router.post("/runs/{run_id}/cancel", response_model=Envelope[AckPayload], responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}})
async def cancel_run(run_id: str, service: RunService = Depends(get_run_service)) -> dict[str, object]:
    session = service.cancel_run(run_id)
    return envelope(map_pause_ack(session, session.host.report()))


@router.post("/runs/{run_id}/instructions", response_model=Envelope[AckPayload], responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}})
async def add_instruction(run_id: str, req: InstructionRequest, service: RunService = Depends(get_run_service)) -> dict[str, object]:
    session = service.add_instruction(run_id, req)
    return envelope(map_instruction_ack(session, session.host.report()))


@router.get("/runs/{run_id}/events", response_model=Envelope[EventsPagePayload], responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}})
async def get_events(
    run_id: str,
    after_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    service: RunService = Depends(get_run_service),
) -> dict[str, object]:
    session, items, total = service.get_events(run_id, after_seq, limit)
    has_more = total > len(items)
    return envelope(map_events(run_id, items, has_more, after_seq=after_seq, limit=limit, total_available=total))


@router.get("/runs/{run_id}/events/stream", responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}})
async def stream_events(
    run_id: str,
    after_seq: int = Query(default=0, ge=0),
    service: RunService = Depends(get_run_service),
) -> StreamingResponse:
    service.get_run(run_id)

    async def _event_stream():
        current = after_seq
        while True:
            session, items, _ = service.get_events(run_id, current, 200)
            mapped = [map_event(run_id, item) for item in items]
            if mapped:
                for item in mapped:
                    current = max(current, int(item.get("seq", current) or current))
                    yield _format_sse_event(item)
            lifecycle = str(session.host.report().get("lifecycle", "") or "idle")
            if lifecycle in {"completed", "paused"} or session.state_override in {"failed", "canceled"}:
                break
            import asyncio
            await asyncio.sleep(0.35)

    return StreamingResponse(_event_stream(), media_type="text/event-stream")


@router.get("/runs/{run_id}/chapters/{chapter_number}", response_model=Envelope[ChapterPayload], responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}})
async def get_chapter(run_id: str, chapter_number: int, service: RunService = Depends(get_run_service)) -> dict[str, object]:
    session, data = service.get_chapter(run_id, chapter_number)
    return envelope(map_chapter(run_id, chapter_number, data["title"], data["content"], data["summary"], data["review"]))


@router.get("/runs/{run_id}/artifacts", response_model=Envelope[ArtifactListPayload], responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}})
async def get_artifacts(
    run_id: str,
    type: str = Query(default=""),
    chapter: int = Query(default=0, ge=0),
    service: RunService = Depends(get_run_service),
) -> dict[str, object]:
    session, items = service.get_artifacts(run_id, artifact_type=type, chapter=chapter)
    return envelope(map_artifacts(session.run_id, items))


def install_error_handlers(app) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        _ = request
        body = {"code": exc.code, "message": exc.message}
        if exc.details:
            body["details"] = exc.details
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(KeyError)
    async def handle_key_error(request: Request, exc: KeyError) -> JSONResponse:
        _ = request
        return JSONResponse(status_code=404, content={"code": "RUN_NOT_FOUND", "message": "run not found", "details": {"run_id": str(exc)}})
