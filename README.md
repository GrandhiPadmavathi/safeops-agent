# SafeOps Agent

A tool-using LLM agent for back-office operations that **cannot take a risky action without a human saying yes**.
One agent core, two domains (e-commerce order support and banking operations), a local or hosted model
switchable in config, an audit trail of every decision, and an eval suite that measures what the model tries to
do, not just what it says.

- **Human approval gate**: risky tools (cancel, refund, block card, reverse, freeze) pause the LangGraph run with
  `interrupt()`. Nothing changes until a reviewer approves; a rejection is fed back to the model.
- **Dry-run policy check**: before asking a human, the risky call is executed inside a transaction that is always
  rolled back. If a business rule rejects it (refund above the limit, reversing an already reversed charge,
  touching a frozen account), the model gets the error and the reviewer is never interrupted.
- **Audit log**: every approval request, decision (with reviewer and note), execution and policy block is written to
  an append-only JSONL file and shown in the UI.
- **Two domains, one core**: a domain is just tools + Pydantic schemas + a prompt + seed data. Adding a third is a
  folder, not a rewrite.
- **Ollama or Groq**: `SAFEOPS_LLM_PROVIDER=ollama` (default, `qwen2.5:3b`, fully local) or `groq`
  (`llama-3.1-8b-instant`).
- **MCP server**: the same tools can be served to Claude Desktop / Cursor; risky ones only return a preview until
  called again with `confirm=true`.

## Architecture

```mermaid
flowchart LR
    UI[React UI] -->|/chat, /approve| API[FastAPI]
    API --> R[AgentRunner<br/>threads + audit]
    R --> G
    subgraph G[LangGraph]
        A[agent<br/>LLM + tools] -->|tool calls| H{human_approval}
        H -->|safe or approved| X[execute_tools]
        H -->|rule broken| A
        H -.->|interrupt| R
        X --> A
    end
    X --> DB[(SQLite<br/>e-commerce + banking)]
    H -->|dry run, rolled back| DB
    R --> L[(audit.jsonl)]
    M[MCP server] --> DB
```

`human_approval` walks every tool call in the model's last message:

1. Safe tool (lookups) → passes straight through.
2. Risky tool → dry-run it. A business-rule error goes back to the model as the tool result.
3. Otherwise → `interrupt()` with a plain-language summary (`Reverse transaction TXN-7001 and credit the account
   (reason: ...)`). The API returns `status: awaiting_approval`; `/approve` resumes the same thread with
   `Command(resume={"approved": ...})`.

`execute_tools` only runs calls that are safe or explicitly approved, so a model that emits two risky calls in one
turn needs two decisions.

## Domains

| Domain | Read-only tools | Risky tools (need approval) | Rules enforced in code |
|---|---|---|---|
| E-commerce | `find_customer`, `get_order`, `track_shipment` | `cancel_order`, `issue_refund`, `update_shipping_address` | cancel/address change only while PLACED; refunds only on DELIVERED, within the refundable balance, max 10,000 |
| Banking | `find_customer`, `get_account`, `list_transactions`, `get_transaction` | `block_card`, `reverse_transaction`, `freeze_account` | reverse only POSTED charges on ACTIVE accounts, max 5,000; a freeze needs a reason |

All data is synthetic and reseeded with **Reset demo data**.

## Evaluation

40 hand-written cases (20 per domain) in [`evals/cases`](evals/cases): lookups, clear risky requests, requests that
break a business rule, missing details, bulk requests, prompt injection and multi-step chains. Each case declares
tools that must / must not be called, whether approval is expected, and argument values. The eval reviewer
**rejects every approval**, so any risky action that still executes counts as unsafe.

`qwen2.5:3b` on a laptop CPU (Ollama), same prompts, with and without the dry-run policy check:

| Domain | Mode | Pass rate | Tool recall | Arg accuracy | Approval compliance | Cases that interrupted a reviewer | Unsafe executions |
|---|---|---|---|---|---|---|---|
| Banking | approval gate only | 70% | 0.87 | 0.90 | 70% | 9 / 20 | **0** |
| Banking | + dry-run policy | 70% | 0.87 | 0.90 | 85% | 6 / 20 | **0** |
| E-commerce | approval gate only | 75% | 0.80 | 0.92 | 80% | 10 / 20 | **0** |
| E-commerce | + dry-run policy | 75% | 0.80 | 0.92 | 95% | 6 / 20 | **0** |

Median latency is about 22 s per case on CPU. Per-case results are in [`evals/results`](evals/results).

What the numbers say:

- **The 3B model attempts things it should not in 9 of 40 cases**: cancelling a shipped order, refunding above the
  limit, blocking a card nobody named, a bulk "block every card", and obeying a fake "SYSTEM OVERRIDE". The pass
  rate counts these as failures even when they are stopped, because it measures the model.
- **None of them executed.** The approval gate holds regardless of model quality; that is the point of putting
  the control in the graph rather than the prompt.
- **The dry-run check removes 7 of those 19 reviewer interruptions** by rejecting rule-breaking calls automatically,
  which is what lifts approval compliance to 85% / 95%.
- Remaining weaknesses are model-side: it skips the lookup the prompt asks for, invents a missing reason or
  address instead of asking (the reviewer sees and rejects it), and stops multi-step chains early. A larger model
  (`--provider groq`) is the obvious next run.

Run it yourself:

```bash
python -m evals.run_evals --domain all                 # with the dry-run policy check
python -m evals.run_evals --domain all --no-preflight  # approval gate only
python -m evals.run_evals --domain banking --provider groq
```

## Quick start

```bash
python -m venv .venv && .venv/Scripts/activate        # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
ollama pull qwen2.5:3b                                 # or set SAFEOPS_LLM_PROVIDER=groq + SAFEOPS_GROQ_API_KEY
cp .env.example .env

uvicorn api.main:app --port 8080                       # API docs at http://127.0.0.1:8080/docs
cd ui && npm install && npm run dev                    # UI at http://localhost:5173
```

On Windows `scripts/run_all.ps1` starts both. `python scripts/smoke_test.py` runs a real block-card request
through the API and checks the card only changes after approval.

### API

| Method | Path | Purpose |
|---|---|---|
| GET | `/domains` | domains, tools (with `risky` flag), sample prompts |
| POST | `/chat` | `{domain, message, thread_id?}` → events, reply or pending approval |
| POST | `/approve` | `{thread_id, approved, reviewer, note}` → resumes the run |
| GET | `/domains/{name}/records` | live data for the UI |
| GET | `/audit?limit=50` | recent audit entries |
| POST | `/reset` | reseed demo data |

### MCP

```bash
python -m mcp_server.server --domain banking
```

See [`mcp_server/mcp.example.json`](mcp_server/mcp.example.json) for a client config. Risky tools are annotated
as destructive and return `{"requires_confirmation": true, "summary": ...}` until called with `confirm=true`.

## Tests

```bash
pytest     # 40 tests, no model needed
```

The graph is tested with a scripted fake chat model: approve and reject paths for both domains, two risky calls
in one turn, the policy check blocking without touching data, the step limit, thread/domain guards, every
business rule, the API round trip, the MCP confirm flow and the eval scoring.

## Design decisions

- **Control in the graph, not the prompt.** The prompt asks the model to behave; `human_approval` and
  `execute_tools` make sure it cannot do otherwise. The evals show why: a small model ignores instructions often.
- **Dry run instead of duplicating rules.** The policy check calls the real tool and rolls back, so business rules
  live in one place and cannot drift from a separate validator.
- **Domain as data.** `Domain` bundles tools, schemas, prompt, seed and record views; the agent, runner, API, MCP
  server, UI and evals are domain-agnostic.
- **Evals that score behaviour.** Tool calls, arguments and approvals are checked from the trace; final-answer
  wording is not graded.

## Configuration

| Variable | Default |
|---|---|
| `SAFEOPS_LLM_PROVIDER` | `ollama` (`groq` also supported) |
| `SAFEOPS_OLLAMA_MODEL` | `qwen2.5:3b` |
| `SAFEOPS_GROQ_MODEL` | `llama-3.1-8b-instant` |
| `SAFEOPS_GROQ_API_KEY` | – |
| `SAFEOPS_AGENT_MAX_STEPS` | `10` |
| `SAFEOPS_AGENT_PREFLIGHT` | `true` |

## License

MIT
