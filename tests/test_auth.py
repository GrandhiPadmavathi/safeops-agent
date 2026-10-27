from datetime import datetime, timedelta, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from api.main import create_app
from safeops.auth import LOCAL_AUDIENCE, LOCAL_ISSUER, LoginThrottle, hash_password, verify_password
from tests.conftest import TEST_SECRET, call, login, make_auth, say

REVERSE = [call("reverse_transaction", transaction_ref="TXN-7001", reason="Duplicate"), say("Reversed.")]


@pytest.fixture
def client_for(make_runner):
    def factory(script, auth=None):
        return TestClient(create_app(runner=make_runner(script), auth=auth or make_auth()))

    return factory


def start_reversal(client, headers) -> str:
    res = client.post("/chat", json={"domain": "banking", "message": "reverse TXN-7001"}, headers=headers)
    assert res.json()["status"] == "awaiting_approval"
    return res.json()["thread_id"]


def test_password_hashes_are_salted_and_verifiable():
    first, second = hash_password("s3cret"), hash_password("s3cret")
    assert first != second and "s3cret" not in first
    assert verify_password("s3cret", first)
    assert not verify_password("wrong", first)
    assert not verify_password("s3cret", "md5$abc$def")


def test_protected_routes_need_a_token(client_for):
    with client_for([say("hi")]) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/domains").status_code == 200
        for method, path in [("post", "/chat"), ("post", "/approve"), ("get", "/approvals"), ("get", "/audit"),
                             ("post", "/reset"), ("get", "/domains/banking/records"), ("get", "/auth/me")]:
            res = client.post(path, json={}) if method == "post" else client.get(path)
            assert res.status_code == 401, path
            assert res.headers["WWW-Authenticate"] == "Bearer"


def test_login_failures_are_generic_audited_and_throttled(client_for, make_runner):
    auth = make_auth()
    auth.throttle = LoginThrottle(max_failures=3, window=60)
    with client_for([say("hi")], auth=auth) as client:
        unknown = client.post("/auth/token", data={"username": "nobody", "password": "x"})
        wrong = client.post("/auth/token", data={"username": "olivia", "password": "x"})
        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json() == wrong.json()

        client.post("/auth/token", data={"username": "olivia", "password": "x"})
        client.post("/auth/token", data={"username": "olivia", "password": "x"})
        locked = client.post("/auth/token", data={"username": "olivia", "password": "pw-olivia"})
        assert locked.status_code == 429

        audit = client.get("/audit", headers=login(client, "admin")).json()
        assert [a["event"] for a in audit].count("login_failed") == 5
        assert all("password" not in a for a in audit)


def test_roles_limit_what_each_user_can_do(client_for):
    with client_for(REVERSE) as client:
        operator, reviewer = login(client, "olivia"), login(client, "ravi")
        thread_id = start_reversal(client, operator)

        assert client.post("/approve", json={"thread_id": thread_id, "approved": True},
                           headers=operator).status_code == 403
        assert client.post("/reset", headers=operator).status_code == 403
        assert client.post("/reset", headers=reviewer).status_code == 403
        assert client.post("/chat", json={"domain": "banking", "message": "hi"}, headers=reviewer).status_code == 403
        assert client.get("/auth/me", headers=reviewer).json()["roles"] == ["reviewer"]

        denied = [a for a in client.get("/audit", headers=reviewer).json() if a["event"] == "access_denied"]
        assert {(a["user"], a["permission"]) for a in denied} >= {("olivia", "approve"), ("ravi", "chat")}


def test_two_person_approval_flow(client_for):
    with client_for(REVERSE) as client:
        operator, reviewer = login(client, "olivia"), login(client, "ravi")
        thread_id = start_reversal(client, operator)

        queue = client.get("/approvals", headers=reviewer).json()
        assert [(q["thread_id"], q["requested_by"], q["can_decide"]) for q in queue] == [(thread_id, "olivia", True)]

        done = client.post("/approve", json={"thread_id": thread_id, "approved": True, "reviewer": "spoofed"},
                           headers=reviewer).json()
        assert done["decision"]["reviewer"] == "ravi"
        assert client.get("/approvals", headers=reviewer).json() == []

        status = client.get(f"/threads/{thread_id}", headers=operator).json()
        assert status["status"] == "completed" and status["reply"] == "Reversed."

        decision = next(a for a in client.get("/audit", headers=reviewer).json() if a["event"] == "approval_decision")
        assert (decision["requested_by"], decision["reviewer"]) == ("olivia", "ravi")


def test_requester_cannot_approve_their_own_action(client_for):
    with client_for(REVERSE) as client:
        admin = login(client, "admin")
        thread_id = start_reversal(client, admin)

        assert client.get("/approvals", headers=admin).json()[0]["can_decide"] is False
        res = client.post("/approve", json={"thread_id": thread_id, "approved": True}, headers=admin)
        assert res.status_code == 403
        assert "another reviewer" in res.json()["detail"]

        records = client.get("/domains/banking/records", headers=admin).json()
        txns = {t["txn"]: t["status"] for t in records["transactions"]}
        assert txns["TXN-7001"] != "REVERSED"
        assert client.get("/audit", headers=admin).json()[-1]["event"] == "approval_denied"


def test_users_cannot_touch_each_others_conversations(client_for):
    with client_for(REVERSE) as client:
        olivia, omar = login(client, "olivia"), login(client, "omar")
        thread_id = start_reversal(client, olivia)

        hijack = client.post("/chat", json={"domain": "banking", "message": "hi", "thread_id": thread_id},
                             headers=omar)
        assert hijack.status_code == 403
        assert client.get(f"/threads/{thread_id}", headers=omar).status_code == 404
        assert client.get("/audit", headers=omar).json() == []
        assert {a["thread_id"] for a in client.get("/audit", headers=olivia).json()} == {thread_id}


def test_tampered_expired_and_foreign_tokens_are_rejected(client_for):
    with client_for([say("hi")]) as client:
        token = login(client, "olivia")["Authorization"].split()[1]
        now = datetime.now(timezone.utc)

        claims = jwt.decode(token, TEST_SECRET, algorithms=["HS256"], audience=LOCAL_AUDIENCE)
        escalated = jwt.encode({**claims, "roles": ["admin"]}, "a-different-secret-of-sufficient-length!", "HS256")
        expired = jwt.encode({**claims, "exp": now - timedelta(minutes=1)}, TEST_SECRET, "HS256")
        foreign = jwt.encode({**claims, "iss": "https://evil.example"}, TEST_SECRET, "HS256")
        unsigned = jwt.encode({**claims, "roles": ["admin"]}, None, algorithm="none")

        for bad, detail in [(escalated, "Invalid token."), (expired, "Token has expired."),
                            (foreign, "Token issuer is not trusted."), (unsigned, "Invalid token."),
                            ("not-a-jwt", "Invalid token.")]:
            res = client.get("/auth/me", headers={"Authorization": f"Bearer {bad}"})
            assert (res.status_code, res.json()["detail"]) == (401, detail)


class StaticJwks:
    def __init__(self, public_key):
        self.key = public_key

    def get_signing_key_from_jwt(self, _token):
        return self


def test_oidc_tokens_from_an_identity_provider(client_for):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    issuer = "https://login.microsoftonline.com/tenant-id/v2.0"
    auth = make_auth(oidc_issuer=issuer, oidc_audience="api://safeops", jwks_client=StaticJwks(key.public_key()))
    now = datetime.now(timezone.utc)

    def entra_token(**overrides):
        claims = {"iss": issuer, "aud": "api://safeops", "sub": "abc123", "preferred_username": "priya@contoso.com",
                  "roles": ["reviewer", "Global.Admin"], "iat": now, "exp": now + timedelta(minutes=5), **overrides}
        return {"Authorization": f"Bearer {jwt.encode(claims, key, algorithm='RS256')}"}

    with client_for([say("hi")], auth=auth) as client:
        assert client.get("/auth/config").json()["oidc_enabled"] is True
        me = client.get("/auth/me", headers=entra_token()).json()
        assert (me["username"], me["roles"], me["method"]) == ("priya@contoso.com", ["reviewer"], "oidc")
        assert client.get("/approvals", headers=entra_token()).status_code == 200

        assert client.get("/auth/me", headers=entra_token(aud="api://other")).status_code == 401
        other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        forged = jwt.encode({"iss": issuer, "aud": "api://safeops", "sub": "x", "roles": ["admin"],
                             "exp": now + timedelta(minutes=5)}, other_key, algorithm="RS256")
        assert client.get("/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_local_tokens_carry_standard_claims(client_for):
    with client_for([say("hi")]) as client:
        body = client.post("/auth/token", data={"username": "ravi", "password": "pw-ravi"}).json()
        claims = jwt.decode(body["access_token"], TEST_SECRET, algorithms=["HS256"], audience=LOCAL_AUDIENCE)
        assert (claims["iss"], claims["sub"], claims["roles"]) == (LOCAL_ISSUER, "ravi", ["reviewer"])
        assert body["expires_in"] == 30 * 60 and claims["exp"] - claims["iat"] == 30 * 60
        assert body["user"]["permissions"] == ["approve", "audit:read", "records:read"]
