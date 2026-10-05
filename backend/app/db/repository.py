"""
Database operations for workflows and executions.
Falls back to in-memory store if PostgreSQL is unavailable.
"""
from __future__ import annotations
import logging
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from .models import WorkflowModel, ExecutionModel
from ..core.dag_schema import WorkflowDefinition

logger = logging.getLogger(__name__)

# ── Fallback in-memory store (used when DB is unavailable) ───────────────────
_mem_workflows: dict[str, dict] = {}
_mem_executions: dict[str, dict] = {}


async def save_workflow(db: AsyncSession | None, wf: WorkflowDefinition) -> WorkflowDefinition:
    data = wf.model_dump()
    if db is None:
        _mem_workflows[wf.workflow_id] = data
        return wf
    row = WorkflowModel(
        workflow_id=wf.workflow_id,
        name=wf.name,
        description=wf.description,
        definition=data,
        created_by=wf.created_by,
    )
    db.add(row)
    await db.commit()
    return wf


async def get_workflow(db: AsyncSession | None, workflow_id: str) -> WorkflowDefinition | None:
    if db is None:
        data = _mem_workflows.get(workflow_id)
        return WorkflowDefinition(**data) if data else None
    result = await db.execute(select(WorkflowModel).where(WorkflowModel.workflow_id == workflow_id))
    row = result.scalar_one_or_none()
    return WorkflowDefinition(**row.definition) if row else None


async def list_workflows(db: AsyncSession | None) -> list[WorkflowDefinition]:
    if db is None:
        return [WorkflowDefinition(**d) for d in _mem_workflows.values()]
    result = await db.execute(select(WorkflowModel).order_by(WorkflowModel.created_at.desc()))
    return [WorkflowDefinition(**row.definition) for row in result.scalars()]


async def update_workflow(db: AsyncSession | None, wf: WorkflowDefinition) -> WorkflowDefinition:
    data = wf.model_dump()
    if db is None:
        _mem_workflows[wf.workflow_id] = data
        return wf
    result = await db.execute(select(WorkflowModel).where(WorkflowModel.workflow_id == wf.workflow_id))
    row = result.scalar_one_or_none()
    if not row:
        return wf
    row.name = wf.name
    row.description = wf.description
    row.definition = data
    await db.commit()
    return wf


async def delete_workflow(db: AsyncSession | None, workflow_id: str) -> None:
    if db is None:
        _mem_workflows.pop(workflow_id, None)
        return
    await db.execute(delete(WorkflowModel).where(WorkflowModel.workflow_id == workflow_id))
    await db.commit()


async def save_execution(db: AsyncSession | None, execution_id: str, workflow_id: str,
                         run_id: str, payload: dict[str, Any]) -> None:
    if db is None:
        _mem_executions[execution_id] = {"execution_id": execution_id, "workflow_id": workflow_id,
                                          "temporal_run_id": run_id, "status": "started"}
        return
    row = ExecutionModel(
        execution_id=execution_id,
        workflow_id=workflow_id,
        temporal_run_id=run_id,
        trigger_payload=payload,
    )
    db.add(row)
    await db.commit()
