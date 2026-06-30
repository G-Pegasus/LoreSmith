from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ainovel_py.internal_api.dto import MetadataSpec


class WorkspaceStory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str = ""
    title: str = ""
    premise: str = ""


class WorkspaceNode(BaseModel):
    node_id: str = ""
    type: str = ""
    title: str = ""
    summary: str = ""
    chapter: int = 0
    asset_type: str = ""


class WorkspaceIntentRequest(BaseModel):
    intent_type: str = Field(min_length=1)
    story: WorkspaceStory = Field(default_factory=WorkspaceStory)
    node: WorkspaceNode = Field(default_factory=WorkspaceNode)
    content: str = ""
    action: str = ""
    instruction: str = ""
    label: str = ""
    payload: dict = Field(default_factory=dict)
    metadata: MetadataSpec = Field(default_factory=MetadataSpec)


class WorkspaceIntentPayload(BaseModel):
    route: str
    result: dict
    fallback_used: bool = False
    reason: str = ""
    provider: str = ""
    model: str = ""
    latency_ms: int = 0
    usage: dict = Field(default_factory=dict)


class WorkspaceIssue(BaseModel):
    id: str
    severity: str
    category: str
    title: str
    description: str
    nodeId: Optional[str] = None
    status: str = "open"


class WorkspaceNodeDto(BaseModel):
    id: str
    parentId: Optional[str] = None
    type: str
    title: str
    order: int = 0
    summary: str = ""


class WorkspaceRunBridgeDto(BaseModel):
    activeRunId: str | None = None
    runAfterSeq: int = 0
    runSyncStatus: str = "idle"
    runSyncUpdatedAt: Optional[str] = None
    lastCompletedChapter: Optional[str] = None


class WorkspaceSnapshotPayload(BaseModel):
    storyId: str
    title: str
    premise: str = ""
    style: str = ""
    updatedAt: Optional[str] = None
    localOnly: bool = False
    nodes: list[WorkspaceNodeDto] = Field(default_factory=list)
    activeNodeId: Optional[str] = None
    contentByNodeId: dict[str, str] = Field(default_factory=dict)
    assistantThread: list[dict] = Field(default_factory=list)
    runBridge: WorkspaceRunBridgeDto = Field(default_factory=WorkspaceRunBridgeDto)


class WorkspaceNodeMutationRequest(BaseModel):
    parentId: Optional[str] = None
    type: str = Field(min_length=1)


class WorkspaceNodeUpdateRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    summary: Optional[str] = None


class WorkspaceRunBridgeUpdateRequest(BaseModel):
    activeRunId: Optional[str] = None
    runAfterSeq: int = 0
    runSyncStatus: str = 'idle'
    runSyncUpdatedAt: Optional[str] = None
    lastCompletedChapter: Optional[str] = None


class WorkspaceAssistantThreadUpdateRequest(BaseModel):
    assistantThread: list[dict] = Field(default_factory=list)
