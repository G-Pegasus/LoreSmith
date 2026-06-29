from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class StoryCharacterSpec(BaseModel):
    name: str = ""
    role: str = ""
    description: str = ""


class StoryWordCountSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_words: int = 2000
    target_words: int = 2500


class StorySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story_id: str = ""
    title: str = ""
    premise: str = ""
    genre: str = ""
    language: str = "zh-CN"
    characters: list[StoryCharacterSpec] = Field(default_factory=list)
    word_count: StoryWordCountSpec = Field(default_factory=StoryWordCountSpec)


class ExecutionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = ""
    model: str = ""
    context_window: int = 0
    temperature: Optional[float] = None


class InputSpec(BaseModel):
    mode: str = "start"
    prompt: str = ""


class CallbackSpec(BaseModel):
    event_url: str = ""
    token: str = ""


class StorageSpec(BaseModel):
    kind: str = "local"
    base_path: str = ""


class MetadataSpec(BaseModel):
    tenant_id: str = ""
    user_id: str = ""
    workspace_id: str = ""
    request_id: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)


class CreateRunRequest(BaseModel):
    run_id: str = Field(min_length=1)
    story: StorySpec = Field(default_factory=StorySpec)
    execution: ExecutionSpec = Field(default_factory=ExecutionSpec)
    input: InputSpec = Field(default_factory=InputSpec)
    callback: CallbackSpec = Field(default_factory=CallbackSpec)
    storage: StorageSpec = Field(default_factory=StorageSpec)
    metadata: MetadataSpec = Field(default_factory=MetadataSpec)
    config_path: str = ""


class ResumeRunRequest(BaseModel):
    reason: str = ""
    decision: str = ""
    feedback: str = ""
    input: InputSpec = Field(default_factory=InputSpec)
    metadata: MetadataSpec = Field(default_factory=MetadataSpec)


class PauseRunRequest(BaseModel):
    reason: str = ""
    metadata: MetadataSpec = Field(default_factory=MetadataSpec)


class InstructionSpec(BaseModel):
    instruction_id: str = ""
    type: str = "follow_up"
    text: str = ""
    decision: str = ""
    feedback: str = ""


class InstructionRequest(BaseModel):
    instruction: InstructionSpec = Field(default_factory=InstructionSpec)
    metadata: MetadataSpec = Field(default_factory=MetadataSpec)
