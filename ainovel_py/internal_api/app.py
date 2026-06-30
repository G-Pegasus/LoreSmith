from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ainovel_py.internal_api.persistence import RunRegistryStore, RunTaskStore
from ainovel_py.internal_api.registry import RunRegistry
from ainovel_py.internal_api.routes import install_error_handlers, router
from ainovel_py.internal_api.service import RunService
from ainovel_py.internal_api.workspace_routes import router as workspace_router
from ainovel_py.internal_api.workspace_service import WorkspaceService
from ainovel_py.internal_api.settings import load_settings
from ainovel_py.internal_api.worker import WorkerManager


def create_app() -> FastAPI:
    app = FastAPI(
        title="ainovel internal api",
        version="0.1.0",
        description="Internal API consumed by the Java platform layer to control and observe the Python agent runtime.",
    )
    settings = load_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:5174",
            "http://localhost:5174",
            "http://127.0.0.1:8080",
            "http://localhost:8080",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    store = RunRegistryStore(settings.registry_path)
    task_store = RunTaskStore(settings.registry_path + ".tasks")
    registry = RunRegistry(store, task_store)
    registry.restore()
    worker = WorkerManager(registry)
    worker.start()
    app.state.settings = settings
    app.state.run_registry = registry
    app.state.run_service = RunService(registry)
    app.state.workspace_service = WorkspaceService()
    app.state.worker_manager = worker
    app.include_router(router)
    app.include_router(workspace_router)
    install_error_handlers(app)
    return app


app = create_app()
