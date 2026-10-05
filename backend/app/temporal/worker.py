"""
Temporal Worker — runs as a separate process alongside the FastAPI server.

Local:    python -m app.temporal.worker
Railway:  automatically started via Procfile (worker process)
"""
import asyncio
import logging
import os

from temporalio.worker import Worker

from .client import get_temporal_client, TEMPORAL_NAMESPACE, TEMPORAL_HOST
from .workflows import WorkflowExecutionWorkflow
from .activities import execute_node

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TASK_QUEUE = os.environ.get("TEMPORAL_TASK_QUEUE", "workflow-builder")


async def main():
    logger.info(f"Connecting to Temporal at {TEMPORAL_HOST} (namespace: {TEMPORAL_NAMESPACE})")
    client = await get_temporal_client()
    logger.info("Connected.")

    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[WorkflowExecutionWorkflow],
        activities=[execute_node],
    )
    logger.info(f"Worker started on task queue: {TASK_QUEUE}")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
