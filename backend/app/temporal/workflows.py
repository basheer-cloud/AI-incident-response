"""
Temporal Workflow — executes a WorkflowDefinition DAG.

Supports:
- Standard tool activities (retried per node retry_policy)
- Human approval nodes (tool == "slack.request_approval") — workflow pauses,
  waits for an approval_signal, then continues or aborts based on decision.
- Conditional edge evaluation
"""
from __future__ import annotations
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy as TemporalRetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from ..core.dag_schema import WorkflowDefinition, NodeStatus
    from .activities import execute_node

APPROVAL_TIMEOUT_SECONDS = int(3600 * 4)  # 4 hours max wait for human approval


def _evaluate_condition(condition: str | None, node_statuses: dict[str, str]) -> bool:
    if condition is None:
        return True
    import re
    m = re.match(r"(\w+)\.status\s*==\s*(\w+)", condition)
    if m:
        node_id, expected = m.group(1), m.group(2)
        return node_statuses.get(node_id, "") == expected
    return True


@workflow.defn(name="WorkflowExecution")
class WorkflowExecutionWorkflow:

    def __init__(self) -> None:
        self._approval_decision: str | None = None  # "approved" | "rejected"

    @workflow.signal(name="approval_signal")
    def approval_signal(self, decision: str) -> None:
        """Receive a human approval decision (approved/rejected)."""
        self._approval_decision = decision

    @workflow.run
    async def run(self, workflow_def: dict, trigger_payload: dict[str, Any]) -> dict[str, Any]:
        wf = WorkflowDefinition(**workflow_def)

        adjacency: dict[str, list[tuple[str, str | None]]] = {}
        for edge in wf.edges:
            src = edge.from_node
            adjacency.setdefault(src, []).append((edge.to_node, edge.condition))

        context: dict[str, Any] = {
            "trigger": {"payload": trigger_payload},
            "workflow_id": wf.workflow_id,
            "execution_id": workflow.info().workflow_id,
        }
        node_statuses: dict[str, str] = {}
        node_map = {n.id: n for n in wf.nodes}

        queue: list[str] = ["trigger"]
        visited: set[str] = set()

        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            for (next_id, condition) in adjacency.get(current, []):
                if not _evaluate_condition(condition, node_statuses):
                    node_statuses[next_id] = NodeStatus.skipped
                    continue

                node = node_map.get(next_id)
                if not node:
                    continue

                # ── Human approval node ───────────────────────────────────────
                if node.tool == "slack.request_approval":
                    self._approval_decision = None

                    # Enrich approval inputs with execution context
                    enriched_inputs = {
                        **node.inputs,
                        "execution_id": workflow.info().workflow_id,
                        "workflow_id": wf.workflow_id,
                    }

                    try:
                        await workflow.execute_activity(
                            execute_node,
                            args=[{**node.model_dump(), "inputs": enriched_inputs}, context],
                            start_to_close_timeout=timedelta(seconds=30),
                            # max 1 attempt — Slack message sends before any failure so a retry
                            # would send a duplicate message before crashing again
                            retry_policy=TemporalRetryPolicy(maximum_attempts=1),
                        )
                    except ActivityError:
                        pass  # Approval request sent best-effort; workflow continues to wait

                    # Wait for signal (up to 4 hours)
                    try:
                        await workflow.wait_condition(
                            lambda: self._approval_decision is not None,
                            timeout=timedelta(seconds=APPROVAL_TIMEOUT_SECONDS),
                        )
                    except Exception:
                        # Timeout — treat as rejected
                        self._approval_decision = "rejected"

                    decision = self._approval_decision or "rejected"
                    context[next_id] = {"output": {"decision": decision}, "status": NodeStatus.success}
                    node_statuses[next_id] = NodeStatus.success

                    if decision == "rejected":
                        # Mark all downstream as skipped
                        workflow.logger.info(f"Approval rejected at node {next_id} — halting workflow")
                        break

                # ── Standard activity node ────────────────────────────────────
                else:
                    rp = node.retry_policy
                    try:
                        output = await workflow.execute_activity(
                            execute_node,
                            args=[node.model_dump(), context],
                            start_to_close_timeout=timedelta(seconds=node.timeout_seconds),
                            retry_policy=TemporalRetryPolicy(
                                maximum_attempts=rp.max_attempts,
                                initial_interval=timedelta(seconds=rp.initial_interval_seconds),
                                maximum_interval=timedelta(seconds=rp.max_interval_seconds),
                            ),
                        )
                        context[next_id] = {"output": output, "status": NodeStatus.success}
                        node_statuses[next_id] = NodeStatus.success
                    except ActivityError as e:
                        context[next_id] = {"output": {}, "status": NodeStatus.failed, "error": str(e)}
                        node_statuses[next_id] = NodeStatus.failed
                        workflow.logger.error(f"Node {next_id} failed: {e}")

                queue.append(next_id)

        return {"node_statuses": node_statuses, "context": context}
