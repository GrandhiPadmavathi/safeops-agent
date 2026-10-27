"""Authentication and role-based authorization for the API.

Local demo users get short-lived HS256 tokens from this service. When OIDC settings are present, RS256 tokens
issued by Microsoft Entra ID, Google or any other OpenID Connect provider are accepted too, verified against the
provider's published signing keys, with roles read from a claim (Entra ID app roles use `roles`).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

log = logging.getLogger(__name__)

LOCAL_ISSUER = "safeops-agent"
LOCAL_AUDIENCE = "safeops-api"

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "operator": frozenset({"chat", "records:read", "audit:read:own"}),
    "reviewer": frozenset({"approve", "records:read", "audit:read"}),
    "admin": frozenset({"chat", "approve", "records:read", "audit:read", "admin:reset"}),
}
DEMO_USERS = {"operator": ("operator",), "reviewer": ("reviewer",), "admin": ("admin",)}


class AuthError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class Principal:
    username: str
    roles: frozenset[str]
    method: str = "local"

    @property
    def permissions(self) -> frozenset[str]:
        return frozenset(p for role in self.roles for p in ROLE_PERMISSIONS.get(role, ()))

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    def public(self) -> dict[str, Any]:
        return {"username": self.username, "roles": sorted(self.roles), "permissions": sorted(self.permissions),
                "method": self.method}


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    candidate = hash_password(password, bytes.fromhex(salt_hex)).split("$")[2]
    return hmac.compare_digest(candidate, digest_hex)


class UserStore:
    def __init__(self, users: dict[str, tuple[str, tuple[str, ...]]] | None = None) -> None:
        self._users = dict(users or {})
        self._dummy_hash = hash_password(secrets.token_urlsafe(16))

    def add(self, username: str, password: str, roles: tuple[str, ...]) -> None:
        unknown = set(roles) - set(ROLE_PERMISSIONS)
        if unknown:
            raise ValueError(f"Unknown roles: {sorted(unknown)}")
        self._users[username] = (hash_password(password), roles)

    def authenticate(self, username: str, password: str) -> Principal | None:
        stored = self._users.get(username)
        # Hash even for unknown users so response time does not reveal which usernames exist.
        ok = verify_password(password, stored[0] if stored else self._dummy_hash)
        if not (ok and stored):
            return None
        return Principal(username, frozenset(stored[1]))

    @property
    def usernames(self) -> list[str]:
        return sorted(self._users)


class LoginThrottle:
    """Locks a username for `window` seconds after `max_failures` failed logins inside that window."""

    def __init__(self, max_failures: int = 5, window: float = 300.0) -> None:
        self.max_failures = max_failures
        self.window = window
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, username: str, now: float) -> list[float]:
        return [t for t in self._failures.get(username, []) if now - t < self.window]

    def locked(self, username: str) -> bool:
        with self._lock:
            return len(self._recent(username, time.monotonic())) >= self.max_failures

    def failed(self, username: str) -> None:
        with self._lock:
            now = time.monotonic()
            self._failures[username] = [*self._recent(username, now), now]

    def succeeded(self, username: str) -> None:
        with self._lock:
            self._failures.pop(username, None)


class TokenService:
    def __init__(
        self,
        secret: str | None = None,
        token_minutes: int = 30,
        oidc_issuer: str | None = None,
        oidc_audience: str | None = None,
        oidc_jwks_url: str | None = None,
        oidc_roles_claim: str = "roles",
        jwks_client: Any = None,
    ) -> None:
        if secret is None:
            secret = secrets.token_urlsafe(48)
            log.warning("SAFEOPS_AUTH_JWT_SECRET is not set; using a random secret, tokens reset on restart.")
        if len(secret) < 32:
            raise ValueError("SAFEOPS_AUTH_JWT_SECRET must be at least 32 characters.")
        self._secret = secret
        self.token_minutes = token_minutes
        self.oidc_issuer = oidc_issuer
        self.oidc_audience = oidc_audience
        self.oidc_roles_claim = oidc_roles_claim
        self._jwks = jwks_client or (jwt.PyJWKClient(oidc_jwks_url) if oidc_issuer and oidc_jwks_url else None)

    @property
    def oidc_enabled(self) -> bool:
        return bool(self.oidc_issuer and self.oidc_audience and self._jwks)

    def issue(self, principal: Principal) -> tuple[str, int]:
        now = datetime.now(timezone.utc)
        claims = {
            "sub": principal.username, "roles": sorted(principal.roles), "iss": LOCAL_ISSUER,
            "aud": LOCAL_AUDIENCE, "iat": now, "exp": now + timedelta(minutes=self.token_minutes),
            "jti": uuid.uuid4().hex,
        }
        return jwt.encode(claims, self._secret, algorithm="HS256"), self.token_minutes * 60

    def verify(self, token: str) -> Principal:
        try:
            issuer = jwt.decode(token, options={"verify_signature": False}).get("iss")
            if issuer == LOCAL_ISSUER:
                claims = jwt.decode(token, self._secret, algorithms=["HS256"], audience=LOCAL_AUDIENCE,
                                    issuer=LOCAL_ISSUER, options={"require": ["exp", "sub"]})
                return Principal(claims["sub"], frozenset(claims.get("roles", [])) & ROLE_PERMISSIONS.keys())
            if self.oidc_enabled and issuer == self.oidc_issuer:
                return self._verify_oidc(token)
        except jwt.ExpiredSignatureError as exc:
            raise AuthError(401, "Token has expired.") from exc
        except jwt.PyJWTError as exc:
            raise AuthError(401, "Invalid token.") from exc
        raise AuthError(401, "Token issuer is not trusted.")

    def _verify_oidc(self, token: str) -> Principal:
        key = self._jwks.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=self.oidc_audience,
                            issuer=self.oidc_issuer, options={"require": ["exp", "sub"]})
        raw = claims.get(self.oidc_roles_claim) or []
        roles = frozenset([raw] if isinstance(raw, str) else raw) & ROLE_PERMISSIONS.keys()
        username = claims.get("preferred_username") or claims.get("email") or claims["sub"]
        return Principal(username, roles, method="oidc")


class AuthService:
    def __init__(self, users: UserStore, tokens: TokenService, throttle: LoginThrottle | None = None) -> None:
        self.users = users
        self.tokens = tokens
        self.throttle = throttle or LoginThrottle()

    @classmethod
    def from_settings(cls, settings: Any) -> AuthService:
        users = UserStore()
        if settings.auth_demo_users:
            for username, roles in DEMO_USERS.items():
                users.add(username, settings.auth_demo_password, roles)
        tokens = TokenService(
            secret=settings.auth_jwt_secret, token_minutes=settings.auth_token_minutes,
            oidc_issuer=settings.oidc_issuer, oidc_audience=settings.oidc_audience,
            oidc_jwks_url=settings.oidc_jwks_url, oidc_roles_claim=settings.oidc_roles_claim,
        )
        return cls(users, tokens)

    def login(self, username: str, password: str) -> tuple[Principal, str, int]:
        if self.throttle.locked(username):
            raise AuthError(429, "Too many failed sign-in attempts. Try again in a few minutes.")
        principal = self.users.authenticate(username, password)
        if principal is None:
            self.throttle.failed(username)
            raise AuthError(401, "Incorrect username or password.")
        self.throttle.succeeded(username)
        token, expires_in = self.tokens.issue(principal)
        return principal, token, expires_in
