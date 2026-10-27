from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

from safeops import __version__
from safeops.audit import AuditLog
from safeops.auth import AuthError, AuthService, Principal
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
    note: str = Field("", max_length=300)


def create_app(
    runner: AgentRunner | None = None, db: Database | None = None, auth: AuthService | None = None
) -> FastAPI:
    db = db or (runner.db if runner else Database(settings.database_url))
    runner = runner or AgentRunner(db, AuditLog(settings.audit_log_path))
    auth = auth or AuthService.from_settings(settings)
    bearer = OAuth2PasswordBearer(tokenUrl="auth/token", auto_error=False)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        seed_all(db)
        yield

    app = FastAPI(title="SafeOps Agent API", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(ConnectionError)
    async def llm_unreachable(_request: Request, exc: ConnectionError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": f"Model provider unreachable: {exc}"})

    @app.exception_handler(AuthError)
    async def auth_failed(_request: Request, exc: AuthError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=headers)

    def current_user(token: str | None = Depends(bearer)) -> Principal:
        if not token:
            raise AuthError(401, "Not authenticated.")
        return auth.tokens.verify(token)

    def require(permission: str, *alternatives: str) -> Callable[..., Principal]:
        def check(request: Request, user: Principal = Depends(current_user)) -> Principal:
            if not any(user.can(p) for p in (permission, *alternatives)):
                runner.audit.record("access_denied", user=user.username, roles=sorted(user.roles),
                                    permission=permission, path=request.url.path)
                raise HTTPException(403, f"Your role does not allow '{permission}'.")
            return user

        return check

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "model": describe_model(), "version": __version__}

    @app.get("/auth/config")
    def auth_config() -> dict:
        return {"demo_users": auth.users.usernames if settings.auth_demo_users else [],
                "oidc_enabled": auth.tokens.oidc_enabled}

    @app.post("/auth/token")
    def login(form: OAuth2PasswordRequestForm = Depends()) -> dict:
        try:
            principal, token, expires_in = auth.login(form.username, form.password)
        except AuthError as exc:
            runner.audit.record("login_failed", user=form.username[:60], status=exc.status_code)
            raise
        runner.audit.record("login", user=principal.username, roles=sorted(principal.roles))
        return {"access_token": token, "token_type": "bearer", "expires_in": expires_in, "user": principal.public()}

    @app.get("/auth/me")
    def me(user: Principal = Depends(current_user)) -> dict:
        return user.public()

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
    def records(name: str, _user: Principal = Depends(require("records:read"))) -> dict:
        try:
            domain = get_domain(name)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        with db.session() as session:
            return domain.records(session)

    @app.post("/chat")
    def chat(body: ChatRequest, user: Principal = Depends(require("chat"))) -> dict:
        try:
            return runner.chat(body.domain, body.message, body.thread_id, user=user.username)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/approvals")
    def approvals(user: Principal = Depends(require("approve"))) -> list[dict]:
        return [{**item, "can_decide": item["requested_by"] != user.username} for item in runner.pending_approvals()]

    @app.post("/approve")
    def approve(body: ApproveRequest, user: Principal = Depends(require("approve"))) -> dict:
        try:
            return runner.approve(body.thread_id, body.approved, user.username, body.note)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/threads/{thread_id}")
    def thread(thread_id: str, user: Principal = Depends(current_user)) -> dict:
        status = runner.thread_status(thread_id)
        if status is None or not (runner.owner(thread_id) == user.username or user.can("approve")):
            raise HTTPException(404, "Conversation not found.")
        return status

    @app.get("/audit")
    def audit(
        limit: int = Query(50, ge=1, le=500), user: Principal = Depends(require("audit:read", "audit:read:own"))
    ) -> list[dict]:
        if user.can("audit:read"):
            return runner.audit.tail(limit)
        own = [e for e in runner.audit.tail(500) if runner.owner(e.get("thread_id", "")) == user.username]
        return own[-limit:]

    @app.post("/reset")
    def reset(user: Principal = Depends(require("admin:reset"))) -> dict:
        seed_all(db, reset=True)
        runner.audit.record("data_reset", user=user.username)
        return {"status": "reset"}

    return app


app = create_app()
