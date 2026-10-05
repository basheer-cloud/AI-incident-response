from __future__ import annotations
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field
import uuid


class TriggerType(str, Enum):
    webhook = "webhook"
    cron = "cron"
    event = "event"
    manual = "manual"


class RetryPolicy(BaseModel):
    max_attempts: int = 3
    backoff: str = "exponential"  # "exponential" | "linear" | "fixed"
    initial_interval_seconds: int = 1
    max_interval_seconds: int = 60


class TriggerConfig(BaseModel):
    type: TriggerType
    config: dict[str, Any] = Field(default_factory=dict)


class NodeStatus(str, Enum):
    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"
    skipped = "skipped"


class Node(BaseModel):
    id: str = Field(default_factory=lambda: f"node_{uuid.uuid4().hex[:8]}")
    name: str
    tool: str  # e.g. "slack.send_message", "http.post", "email.send"
    inputs: dict[str, Any] = Field(default_factory=dict)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    timeout_seconds: int = 30
    description: str = ""


class Edge(BaseModel):
    from_node: str = Field(alias="from")
    to_node: str = Field(alias="to")
    condition: str | None = None  # e.g. "node_1.status == success"

    model_config = {"populate_by_name": True}


class WorkflowDefinition(BaseModel):
    workflow_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str = ""
    trigger: TriggerConfig
    nodes: list[Node]
    edges: list[Edge]
    created_by: str = "user"
    tags: list[str] = Field(default_factory=list)


class WorkflowExecution(BaseModel):
    execution_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    workflow_id: str
    status: NodeStatus = NodeStatus.pending
    node_statuses: dict[str, NodeStatus] = Field(default_factory=dict)
    node_outputs: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
