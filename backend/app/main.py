import os
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api.routes.workflows import router as workflows_router
from .api.routes.approvals import router as approvals_router
from .api.routes.webhooks import router as webhooks_router

app = FastAPI(
    title="AI Incident Response Operator",
    description="Autonomous incident triage and response with Temporal-backed durable execution",
    version="0.2.0",
)

_raw_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:3000")
_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workflows_router, prefix="/api/v1")
app.include_router(approvals_router, prefix="/api/v1")
app.include_router(webhooks_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.2.0"}
