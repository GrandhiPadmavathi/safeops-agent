"""End-to-end check against a running API and a real model.

    python -m uvicorn api.main:app --port 8080
    python scripts/smoke_test.py
"""
from __future__ import annotations

import os
import sys

import httpx

BASE = "http://127.0.0.1:8080"
PASSWORD = os.environ.get("SAFEOPS_AUTH_DEMO_PASSWORD", "safeops-demo")


def login(client: httpx.Client, username: str) -> dict[str, str]:
    res = client.post("/auth/token", data={"username": username, "password": PASSWORD})
    res.raise_for_status()
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=300) as client:
        print("health:", client.get("/health").json())
        operator, reviewer = login(client, "operator"), login(client, "reviewer")
        client.post("/reset", headers=login(client, "admin"))

        first = client.post("/chat", json={"domain": "banking",
                                           "message": "Customer lost card CARD-4242, please block it."},
                            headers=operator).json()
        print("status:", first["status"], "| approval:", (first["approval"] or {}).get("summary"))
        if first["status"] != "awaiting_approval":
            print("FAIL: expected the agent to pause for approval")
            return 1

        def cards() -> dict[str, str]:
            rows = client.get("/domains/banking/records", headers=reviewer).json()["cards"]
            return {c["card"]: c["status"] for c in rows}

        if cards()["CARD-4242"] != "ACTIVE":
            print("FAIL: card changed before approval")
            return 1
        if client.post("/approve", json={"thread_id": first["thread_id"], "approved": True},
                       headers=operator).status_code != 403:
            print("FAIL: an operator was able to approve")
            return 1

        done = client.post("/approve", json={"thread_id": first["thread_id"], "approved": True},
                           headers=reviewer).json()
        print("reply:", done["reply"], "| decided by:", done["decision"]["reviewer"])
        print("CARD-4242:", cards()["CARD-4242"])
        print("audit:", [a["event"] for a in client.get("/audit", params={"limit": 4}, headers=reviewer).json()])
        return 0 if cards()["CARD-4242"] == "BLOCKED" else 1


if __name__ == "__main__":
    sys.exit(main())
