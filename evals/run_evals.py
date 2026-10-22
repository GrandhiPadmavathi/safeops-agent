"""Run the agent against the eval cases with a real model and report metrics.

    python -m evals.run_evals --domain all
    python -m evals.run_evals --domain banking --provider groq
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from evals.scoring import Trace, score_case, summarize
from safeops.audit import AuditLog
from safeops.bootstrap import seed_all
from safeops.config import Settings
from safeops.db import Database
from safeops.domains import DOMAINS, get_domain
from safeops.llm import describe_model, make_llm
from safeops.runner import AgentRunner

HERE = Path(__file__).parent
MAX_DECISIONS = 4


def load_cases(domain: str) -> list[dict[str, Any]]:
    return json.loads((HERE / "cases" / f"{domain}.json").read_text(encoding="utf-8"))


def run_case(domain: str, case: dict[str, Any], cfg: Settings, audit_dir: Path) -> Trace:
    db = Database("sqlite:///:memory:")
    seed_all(db)
    runner = AgentRunner(db, AuditLog(audit_dir / f"{case['id']}.jsonl"), llm_factory=lambda _d: make_llm(cfg),
                         preflight=cfg.agent_preflight)
    risky = get_domain(domain).risky_tool_names
    approve = bool(case.get("approve", False))
    trace = Trace()
    approved_tools: set[str] = set()

    start = time.perf_counter()
    try:
        out = runner.chat(domain, case["message"])
        for _ in range(MAX_DECISIONS + 1):
            for e in out["events"]:
                if e["type"] == "tool_call":
                    trace.calls.append({"tool": e["tool"], "arguments": e["arguments"]})
                elif e["type"] == "approval_required":
                    trace.approvals.append(e["tool_name"])
                elif e["type"] == "tool_result" and e["tool"] in risky and not e["rejected"]:
                    result = e["result"]
                    if e.get("blocked"):
                        trace.blocked.append(e["tool"])
                    elif not (isinstance(result, dict) and "error" in result):
                        trace.executed_risky.append({"tool": e["tool"], "approved": e["tool"] in approved_tools})
            if out["status"] != "awaiting_approval":
                trace.reply = out["reply"]
                break
            if approve:
                approved_tools.add(out["approval"]["tool_name"])
            out = runner.approve(out["thread_id"], approve, reviewer="eval")
        else:
            trace.error = "too many approval rounds"
    except Exception as exc:  # report, keep going
        trace.error = f"{type(exc).__name__}: {exc}"
    trace.latency_s = time.perf_counter() - start
    return trace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", choices=[*sorted(DOMAINS), "all"], default="all")
    parser.add_argument("--provider", choices=["ollama", "groq"], default=None)
    parser.add_argument("--case", action="append", help="Only run these case ids")
    parser.add_argument("--no-preflight", action="store_true", help="Disable the dry-run policy check")
    args = parser.parse_args()

    overrides: dict[str, Any] = {"agent_preflight": not args.no_preflight}
    if args.provider:
        overrides["llm_provider"] = args.provider
    cfg = Settings(**overrides)
    model = describe_model(cfg)
    mode = "preflight" if cfg.agent_preflight else "approval-only"
    domains = sorted(DOMAINS) if args.domain == "all" else [args.domain]
    results_dir = HERE / "results"
    results_dir.mkdir(exist_ok=True)
    overall: dict[str, Any] = {"model": model, "mode": mode, "domains": {}}

    with tempfile.TemporaryDirectory() as tmp:
        for domain in domains:
            cases = [c for c in load_cases(domain) if not args.case or c["id"] in args.case]
            results = []
            for case in cases:
                trace = run_case(domain, case, cfg, Path(tmp))
                r = score_case(case, trace)
                r["category"] = case.get("category", "")
                results.append(r)
                mark = "PASS" if r["passed"] else "FAIL " + ",".join(r["failed_checks"])
                print(f"[{domain}] {r['id']:<26} {mark:<28} {r['latency_s']:>6.1f}s  calls={r['called']}",
                      flush=True)
            summary = summarize(results)
            overall["domains"][domain] = summary
            safe_model = model.replace(":", "_").replace("/", "_")
            (results_dir / f"{domain}__{safe_model}__{mode}.json").write_text(
                json.dumps({"model": model, "mode": mode, "summary": summary, "results": results}, indent=2),
                encoding="utf-8")
            print(f"\n[{domain}] {json.dumps(summary)}\n", flush=True)

    print(json.dumps(overall, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
