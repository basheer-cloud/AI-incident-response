"""
Temporal Activities — each node in the DAG becomes one activity.
Activities are retried automatically by Temporal based on the node's retry policy.
"""
from __future__ import annotations
import logging
import re
from typing import Any
from temporalio import activity
from ..core.dag_schema import Node
from ..tools.registry import get_tool

logger = logging.getLogger(__name__)


def _resolve_template(value: Any, context: dict[str, Any]) -> Any:
    """
    Replace {{path.to.key}} placeholders with values from context dict.

    Single-tag rule: if the entire string is exactly one {{...}} reference,
    return the resolved value as its native type (list, dict, int, etc.) rather
    than stringifying it. This lets logs/arrays pass through intact.

    Mixed strings (e.g. "Hello {{name}}") still do string substitution as before.
    """
    if isinstance(value, str):
        # ── Single-tag shortcut — preserve native type ────────────────────────
        single = re.fullmatch(r"\{\{(.+?)\}\}", value.strip())
        if single:
            path = single.group(1).strip().split(".")
            node: Any = context
            for key in path:
                if isinstance(node, dict):
                    node = node.get(key)
                else:
                    node = None
                    break
            if node is not None:
                return node
            # Key not found — fall through to return the original placeholder

        # ── Multi-part string — substitute and stringify ──────────────────────
        def replacer(match: re.Match) -> str:
            path = match.group(1).strip().split(".")
            node = context
            for key in path:
                if isinstance(node, dict):
                    node = node.get(key, match.group(0))
                else:
                    return match.group(0)
            return str(node)
        return re.sub(r"\{\{(.+?)\}\}", replacer, value)

    if isinstance(value, dict):
        return {k: _resolve_template(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_template(v, context) for v in value]
    return value


@activity.defn(name="execute_node")
async def execute_node(node_dict: dict, execution_context: dict[str, Any]) -> dict[str, Any]:
    """
    Execute a single workflow node.
    node_dict: serialized Node model
    execution_context: {"trigger": {...}, "node_<id>": {"output": {...}}, ...}
    """
    node = Node(**node_dict)
    activity.logger.info(f"Executing node {node.id} ({node.tool})")

    # Warn early if trigger payload is empty — means frontend sent {} (cache issue)
    trigger_payload = execution_context.get("trigger", {}).get("payload", {})
    if not trigger_payload:
        activity.logger.warning(
            f"Node {node.id}: trigger.payload is EMPTY — template vars like "
            f"{{{{trigger.payload.service}}}} will not resolve. "
            f"Likely cause: old frontend JS cached in browser (hard-refresh needed)."
        )

    resolved_inputs = _resolve_template(node.inputs, execution_context)

    # Inject execution_id and workflow_id into every tool call so Slack messages
    # show the right context and approval buttons can signal the correct workflow.
    info = activity.info()
    resolved_inputs.setdefault("execution_id", execution_context.get("execution_id", info.workflow_id))
    resolved_inputs.setdefault("workflow_id", execution_context.get("workflow_id", "unknown"))

    tool_fn = get_tool(node.tool)
    output = await tool_fn(resolved_inputs)

    activity.logger.info(f"Node {node.id} completed: {output}")
    return output
