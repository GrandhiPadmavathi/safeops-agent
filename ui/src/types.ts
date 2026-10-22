export type Tool = { name: string; risky: boolean; description: string };
export type DomainInfo = { name: string; title: string; description: string; sample_prompts: string[]; tools: Tool[] };
export type Approval = { tool_name: string; arguments: Record<string, unknown>; summary: string };
export type AgentEvent =
  | { type: "tool_call"; tool: string; arguments: Record<string, unknown>; risky: boolean }
  | { type: "tool_result"; tool: string; result: unknown; rejected: boolean; blocked?: boolean }
  | ({ type: "approval_required" } & Approval);
export type AgentResponse = {
  thread_id: string;
  status: "awaiting_approval" | "completed";
  events: AgentEvent[];
  reply: string;
  approval: Approval | null;
};
export type Row = Record<string, string | number | null>;
export type AuditEntry = {
  ts: string;
  event: string;
  domain?: string;
  tool?: string;
  decision?: string;
  summary?: string;
};
export type Message =
  | { kind: "user"; text: string }
  | { kind: "agent"; text: string }
  | { kind: "event"; event: AgentEvent };
