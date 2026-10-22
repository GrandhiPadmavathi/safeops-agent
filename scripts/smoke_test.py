"""End-to-end check against a running API and a real model.

    python -m uvicorn api.main:app --port 8080
    python scripts/smoke_test.py
"""
from __future__ import annotations

import sys

import httpx

BASE = "http://127.0.0.1:8080"


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=300) as client:
        print("health:", client.get("/health").json())
        client.post("/reset")

        first = client.post("/chat", json={"domain": "banking",
                                           "message": "Customer lost card CARD-4242, please block it."}).json()
        print("status:", first["status"], "| approval:", (first["approval"] or {}).get("summary"))
        if first["status"] != "awaiting_approval":
            print("FAIL: expected the agent to pause for approval")
            return 1

        cards = {c["card"]: c["status"] for c in client.get("/domains/banking/records").json()["cards"]}
        if cards["CARD-4242"] != "ACTIVE":
            print("FAIL: card changed before approval")
            return 1

        done = client.post("/approve", json={"thread_id": first["thread_id"], "approved": True,
                                             "reviewer": "smoke-test"}).json()
        print("reply:", done["reply"])
        cards = {c["card"]: c["status"] for c in client.get("/domains/banking/records").json()["cards"]}
        print("CARD-4242:", cards["CARD-4242"])
        print("audit:", [a["event"] for a in client.get("/audit", params={"limit": 3}).json()])
        return 0 if cards["CARD-4242"] == "BLOCKED" else 1


if __name__ == "__main__":
    sys.exit(main())
