"""
NL → WorkflowDefinition via Claude with JSON schema constraint + few-shot examples.
"""
from __future__ import annotations
import json
from anthropic import Anthropic
from .dag_schema import WorkflowDefinition

SYSTEM_PROMPT = """You are a workflow compiler. Convert natural language workflow descriptions into structured JSON DAGs.

Available tools (use EXACT names):
- slack.send_message       inputs: channel (str), text (str)
- email.send               inputs: to (str), subject (str), body (str)
- http.post                inputs: url (str), payload (dict)
- http.get                 inputs: url (str), params (dict)
- jira.create_ticket       inputs: project (str), summary (str), description (str), priority (str)
- zendesk.create_ticket    inputs: subject (str), description (str), priority (str)
- github.create_issue      inputs: repo (str), title (str), body (str)
- stripe.retry_payment     inputs: payment_intent_id (str)
- notion.create_page       inputs: database_id (str), title (str), content (str)
- openai.summarize         inputs: text (str), instructions (str)

Template variables in inputs:
- {{trigger.payload.field}}     — field from the triggering event payload
- {{node_1.output.field}}       — output field from a previous node

Output ONLY valid JSON. No markdown, no explanation. Schema:
{
  "name": "string — short workflow name",
  "description": "string — one sentence describing what this workflow does",
  "trigger": {"type": "webhook|cron|event|manual", "config": {}},
  "nodes": [
    {
      "id": "node_1",
      "name": "string — human label",
      "tool": "exact.tool_name",
      "inputs": {"key": "value or {{template}}"},
      "retry_policy": {"max_attempts": 3, "backoff": "exponential", "initial_interval_seconds": 1, "max_interval_seconds": 60},
      "timeout_seconds": 30,
      "description": "string — what this step does"
    }
  ],
  "edges": [
    {"from": "trigger", "to": "node_1"},
    {"from": "node_1", "to": "node_2", "condition": "node_1.status == success"}
  ]
}

Rules:
1. Always include an edge from "trigger" to the first node
2. Node IDs must be sequential: node_1, node_2, node_3...
3. All external API calls get retry_policy with max_attempts: 3
4. For conditional paths (on success / on failure), add a condition field to the edge
5. cron trigger config should include: {"schedule": "0 9 * * 1"} (standard cron expression)
6. webhook trigger config can be empty {}"""

# Few-shot examples shown as conversation turns — this is the single biggest quality lever
FEW_SHOT: list[dict] = [
    {
        "role": "user",
        "content": "When a Stripe payment fails, send a Slack alert to #finance and create a Jira ticket with high priority"
    },
    {
        "role": "assistant",
        "content": json.dumps({
            "name": "Stripe Payment Failure Handler",
            "description": "When a Stripe payment fails, sends a Slack alert to #finance and creates a high-priority Jira ticket for tracking.",
            "trigger": {"type": "webhook", "config": {}},
            "nodes": [
                {
                    "id": "node_1",
                    "name": "Send Slack Alert to #finance",
                    "tool": "slack.send_message",
                    "inputs": {
                        "channel": "#finance",
                        "text": "Payment failed for customer {{trigger.payload.customer_id}} — amount: ${{trigger.payload.amount}}. Payment intent: {{trigger.payload.payment_intent_id}}"
                    },
                    "retry_policy": {"max_attempts": 3, "backoff": "exponential", "initial_interval_seconds": 1, "max_interval_seconds": 60},
                    "timeout_seconds": 15,
                    "description": "Notify the #finance Slack channel with details about the failed payment"
                },
                {
                    "id": "node_2",
                    "name": "Create Jira Ticket",
                    "tool": "jira.create_ticket",
                    "inputs": {
                        "project": "FIN",
                        "summary": "Payment failure — {{trigger.payload.customer_id}}",
                        "description": "Stripe payment failed for {{trigger.payload.customer_id}}. Amount: {{trigger.payload.amount}}. Investigate and retry.",
                        "priority": "High"
                    },
                    "retry_policy": {"max_attempts": 3, "backoff": "exponential", "initial_interval_seconds": 1, "max_interval_seconds": 60},
                    "timeout_seconds": 30,
                    "description": "Create a high-priority Jira ticket in the FIN project to track the payment failure"
                }
            ],
            "edges": [
                {"from": "trigger", "to": "node_1"},
                {"from": "node_1", "to": "node_2", "condition": "node_1.status == success"}
            ]
        }, indent=2)
    },
    {
        "role": "user",
        "content": "Every Monday morning at 9am, summarize last week's tasks and email the team at team@company.com"
    },
    {
        "role": "assistant",
        "content": json.dumps({
            "name": "Weekly Task Summary Email",
            "description": "Every Monday at 9am, fetches last week's tasks, summarizes them with AI, and emails the summary to the team.",
            "trigger": {"type": "cron", "config": {"schedule": "0 9 * * 1", "timezone": "UTC"}},
            "nodes": [
                {
                    "id": "node_1",
                    "name": "Fetch Last Week's Tasks",
                    "tool": "http.get",
                    "inputs": {
                        "url": "https://api.example.com/tasks",
                        "params": {"completed_after": "{{trigger.payload.week_start}}", "completed_before": "{{trigger.payload.week_end}}"}
                    },
                    "retry_policy": {"max_attempts": 3, "backoff": "exponential", "initial_interval_seconds": 1, "max_interval_seconds": 60},
                    "timeout_seconds": 30,
                    "description": "Retrieve all tasks completed in the previous week from the task management API"
                },
                {
                    "id": "node_2",
                    "name": "Summarize Tasks with AI",
                    "tool": "openai.summarize",
                    "inputs": {
                        "text": "{{node_1.output.body}}",
                        "instructions": "Summarize these completed tasks in a concise weekly digest format suitable for a team email. Group by category if possible."
                    },
                    "retry_policy": {"max_attempts": 2, "backoff": "exponential", "initial_interval_seconds": 1, "max_interval_seconds": 30},
                    "timeout_seconds": 60,
                    "description": "Use AI to generate a human-readable summary of last week's completed tasks"
                },
                {
                    "id": "node_3",
                    "name": "Email Summary to Team",
                    "tool": "email.send",
                    "inputs": {
                        "to": "team@company.com",
                        "subject": "Weekly Task Summary",
                        "body": "{{node_2.output.summary}}"
                    },
                    "retry_policy": {"max_attempts": 3, "backoff": "exponential", "initial_interval_seconds": 1, "max_interval_seconds": 60},
                    "timeout_seconds": 30,
                    "description": "Send the AI-generated summary to the team email address"
                }
            ],
            "edges": [
                {"from": "trigger", "to": "node_1"},
                {"from": "node_1", "to": "node_2", "condition": "node_1.status == success"},
                {"from": "node_2", "to": "node_3", "condition": "node_2.status == success"}
            ]
        }, indent=2)
    },
]

AMBIGUITY_PROMPT = """Determine if a workflow description is specific enough to build without asking the user questions.
It IS clear enough if it mentions: what triggers the workflow, what tools/actions to use, any destinations (channels, emails, etc).
It NEEDS clarification only if a critical piece is missing that would prevent building it at all.

Return ONLY JSON — no explanation:
{"needs_clarification": false}
OR
{"needs_clarification": true, "question": "single specific question"}"""


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


def parse_workflow(description: str) -> WorkflowDefinition:
    client = Anthropic()
    messages = FEW_SHOT + [{"role": "user", "content": description}]
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    data = json.loads(_strip_fences(response.content[0].text))

    # Normalize edges — handle from_node/to_node aliases
    data["edges"] = [
        {
            "from": e.get("from", e.get("from_node", "")),
            "to": e.get("to", e.get("to_node", "")),
            "condition": e.get("condition"),
        }
        for e in data.get("edges", [])
    ]
    return WorkflowDefinition(**data)


def check_ambiguity(description: str) -> dict:
    client = Anthropic()
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        system=AMBIGUITY_PROMPT,
        messages=[{"role": "user", "content": description}],
    )
    return json.loads(_strip_fences(response.content[0].text))
