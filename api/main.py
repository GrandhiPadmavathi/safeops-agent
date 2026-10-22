from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from safeops import __version__
from safeops.audit import AuditLog
from safeops.bootstrap import seed_all
from safeops.config import settings
from safeops.db import Database
from safeops.domains import DOMAINS, get_domain
from safeops.llm import describe_model
from safeops.runner import AgentRunner


class ChatRequest(BaseModel):
    domain: str
    message: str = Field(..., min_length=1, max_length=2000)
    thread_id: str | None = None


class ApproveRequest(BaseModel):
    thread_id: str
    approved: bool
    reviewer: str = Field("reviewer", max_length=60)
    note: str = Field("", max_length=300)


def create_app(runner: AgentRunner | None = None, db: Database | None = None) -> FastAPI:
    db = db or (runner.db if runner else Database(settings.database_url))
    runner = runner or AgentRunner(db, AuditLog(settings.audit_log_path))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        seed_all(db)
        yield

    app = FastAPI(title="SafeOps Agent API", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ConnectionError)
    async def llm_unreachable(_request: Request, exc: ConnectionError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": f"Model provider unreachable: {exc}"})

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "model": describe_model(), "version": __version__}

    @app.get("/domains")
    def domains() -> list[dict]:
        return [
            {
                "name": d.name,
                "title": d.title,
                "description": d.description,
                "sample_prompts": d.sample_prompts,
                "tools": [{"name": t.name, "risky": t.risky, "description": t.description} for t in d.tools],
            }
            for d in DOMAINS.values()
        ]

    @app.get("/domains/{name}/records")
    def records(name: str) -> dict:
        try:
            domain = get_domain(name)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        with db.session() as session:
            return domain.records(session)

    @app.post("/chat")
    def chat(body: ChatRequest) -> dict:
        try:
            return runner.chat(body.domain, body.message, body.thread_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/approve")
    def approve(body: ApproveRequest) -> dict:
        try:
            return runner.approve(body.thread_id, body.approved, body.reviewer, body.note)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/audit")
    def audit(limit: int = Query(50, ge=1, le=500)) -> list[dict]:
        return runner.audit.tail(limit)

    @app.post("/reset")
    def reset() -> dict:
        seed_all(db, reset=True)
        return {"status": "reset"}

    return app


app = create_app()
