"""
Shared Temporal client factory.
Supports both local dev server and Temporal Cloud (API key auth).

Environment variables:
  TEMPORAL_HOST       — host:port  (default: localhost:7233)
  TEMPORAL_NAMESPACE  — namespace  (default: "default")
  TEMPORAL_API_KEY    — Temporal Cloud API key (leave blank for local)
"""
from __future__ import annotations
import os
from temporalio.client import Client

TEMPORAL_HOST = os.environ.get("TEMPORAL_HOST", "localhost:7233")
TEMPORAL_NAMESPACE = os.environ.get("TEMPORAL_NAMESPACE", "default")
TEMPORAL_API_KEY = os.environ.get("TEMPORAL_API_KEY", "")


async def get_temporal_client() -> Client:
    """Return a connected Temporal client — cloud or local depending on env."""
    if TEMPORAL_API_KEY:
        return await Client.connect(
            TEMPORAL_HOST,
            namespace=TEMPORAL_NAMESPACE,
            api_key=TEMPORAL_API_KEY,
            tls=True,
        )
    # Local dev server (no auth, no TLS)
    return await Client.connect(TEMPORAL_HOST, namespace=TEMPORAL_NAMESPACE)
