from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FlexibleModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class Viewport(FlexibleModel):
    width: int | None = None
    height: int | None = None


class EventContext(FlexibleModel):
    app_name: str | None = None
    window_title: str | None = None
    url: str | None = None
    title: str | None = None
    viewport: Viewport | None = None
    tab_id: int | None = None


class SessionCreate(FlexibleModel):
    session_id: str
    source: str = "frontend_tracker"
    started_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class EventIn(FlexibleModel):
    session_id: str
    source: str = "frontend_tracker"
    event_type: str
    timestamp: str | None = None
    sequence: int | None = None
    context: EventContext = Field(default_factory=EventContext)
    payload: dict[str, Any] = Field(default_factory=dict)


class EventBatchIn(FlexibleModel):
    events: list[EventIn] = Field(default_factory=list)


class RrwebChunkIn(FlexibleModel):
    session_id: str
    source: str = "frontend_tracker"
    timestamp: str | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)
    context: EventContext = Field(default_factory=EventContext)


class ScreenRecordingChunkIn(FlexibleModel):
    session_id: str
    source: str = "browser_extension"
    timestamp: str | None = None
    chunk_index: int
    mime_type: str = "video/webm"
    data_base64: str
    final: bool = False
    context: EventContext = Field(default_factory=EventContext)
