"""
Validates a WorkflowDefinition before saving.
Returns a list of warning strings (non-fatal) or raises ValueError for fatal issues.
"""
from __future__ import annotations
from .dag_schema import WorkflowDefinition
from ..tools.registry import _registry as TOOL_REGISTRY


def validate_workflow(wf: WorkflowDefinition) -> list[str]:
    warnings: list[str] = []
    node_ids = {n.id for n in wf.nodes}
    edge_sources = {e.from_node for e in wf.edges}
    edge_targets = {e.to_node for e in wf.edges}

    # Every node must be reachable from trigger
    if wf.nodes and "trigger" not in edge_sources:
        warnings.append("No edges from 'trigger' — workflow will never execute any node")

    for node in wf.nodes:
        # Tool must exist in registry
        if node.tool not in TOOL_REGISTRY:
            warnings.append(f"Node '{node.id}' uses unknown tool '{node.tool}'")

        # Node must appear in at least one edge
        if node.id not in edge_sources and node.id not in edge_targets:
            warnings.append(f"Node '{node.id}' is disconnected (not referenced in any edge)")

    # All edge endpoints must be valid node IDs or "trigger"
    valid_ids = node_ids | {"trigger"}
    for edge in wf.edges:
        if edge.from_node not in valid_ids:
            warnings.append(f"Edge references unknown source '{edge.from_node}'")
        if edge.to_node not in valid_ids:
            warnings.append(f"Edge references unknown target '{edge.to_node}'")

    return warnings
