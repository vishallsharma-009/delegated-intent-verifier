const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export interface Mandate {
  mandate_id: string;
  user_id: string;
  raw_text: string;
  total_limit: number;
  remaining_limit: number;
  valid_from: string;
  valid_to: string;
  allowed_categories: string[];
  excluded_categories: string[];
  per_transaction_limit?: number;
  status: string;
  created_at: string;
  intent_profile?: {
    intent_id: string;
    purpose: string;
    allowed_categories: string[];
    excluded_categories: string[];
    expected_amount_range: number[];
    expected_frequency: string;
    expected_transactions_per_period: number;
    typical_merchant_types: string[];
    time_pattern: string;
    notes?: string;
  };
}

export interface ScoreBreakdown {
  category_match: number;
  amount_deviation: number;
  frequency_deviation: number;
  merchant_familiarity: number;
  time_pattern_fit: number;
  velocity_proximity: number;
  intent_similarity: number;
}

export interface TransactionEvaluation {
  transaction_id: string;
  idempotency_key: string;
  state: string;
  final_decision: "APPROVE" | "STEP_UP" | "BLOCK";
  intent_fit_score: number;
  score_breakdown: ScoreBreakdown;
  hard_rule_triggered?: string;
  reason_text: string;
  ai_explanation_text: string;
  step_up_id?: string;
  payment_reference?: string;
}

export interface TransactionSummary {
  transaction_id: string;
  idempotency_key: string;
  user_id: string;
  mandate_id: string;
  agent_id: string;
  merchant_id: string;
  merchant_category: string;
  amount: number;
  timestamp: string;
  stated_intent: string;
  state: string;
  final_decision: "APPROVE" | "STEP_UP" | "BLOCK";
  intent_fit_score: number;
  score_breakdown: ScoreBreakdown;
  ai_explanation_text: string;
  step_up_id?: string;
  step_up_resolution?: string;
}

export interface MetricDetail {
  precision: number;
  recall: number;
  f1_score: number;
  false_approval_rate: number;
  false_block_rate: number;
  false_step_up_rate: number;
  unsafe_action_rate: number;
}

export interface MetricsResponse {
  div_metrics: MetricDetail;
  baseline_1_metrics: MetricDetail;
  baseline_2_metrics: MetricDetail;
  total_evaluated: number;
  avg_latency_ms: number;
  evaluated_at: string;
}

export interface AuditLogItem {
  audit_id: string;
  transaction_id: string;
  mandate_id: string;
  user_id: string;
  agent_id: string;
  event_type: string;
  payload: Record<string, any>;
  created_at: string;
}

export interface RedTeamAttackResult {
  attack_name: string;
  transaction_description: string;
  decision: "APPROVE" | "STEP_UP" | "BLOCK" | "REJECTED";
  intent_fit_score: number;
  hard_rule_triggered?: string;
  reason: string;
  unsafe: boolean;
}


export interface RedTeamSummary {
  attacks_run: number;
  blocked: number;
  step_up: number;
  approved: number;
  unsafe_actions: number;
  results: RedTeamAttackResult[];
  disclaimer: string;
}

export interface AgentReplayItem {
  transaction_id: string;
  timestamp: string;
  amount: number;
  merchant_id: string;
  merchant_category: string;
  stated_intent: string;
  decision: string;
  intent_fit_score: number;
  hard_rule_triggered?: string;
  state: string;
}

export interface AgentReplayResponse {
  agent_id: string;
  mandate_id: string;
  mandate_summary: string;
  total_transactions: number;
  approved_count: number;
  step_up_count: number;
  blocked_count: number;
  hard_violations_count: number;
  behaviour_consistency: "HIGH" | "MODERATE" | "LOW";
  timeline: AgentReplayItem[];
}

export async function fetchMandates(): Promise<Mandate[]> {
  const resp = await fetch(`${API_BASE_URL}/mandates`);
  if (!resp.ok) throw new Error("Failed to fetch mandates");
  return resp.json();
}

export async function createMandate(data: {
  user_id: string;
  raw_text: string;
  total_limit: number;
  allowed_categories: string[];
  excluded_categories: string[];
  per_transaction_limit?: number;
}): Promise<Mandate> {
  const resp = await fetch(`${API_BASE_URL}/mandates`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data)
  });
  if (!resp.ok) throw new Error("Failed to create mandate");
  return resp.json();
}

export async function revokeMandate(mandateId: string): Promise<Mandate> {
  const resp = await fetch(`${API_BASE_URL}/mandates/${mandateId}/revoke`, {
    method: "POST"
  });
  if (!resp.ok) throw new Error("Failed to revoke mandate");
  return resp.json();
}

export async function evaluateTransaction(data: {
  idempotency_key: string;
  user_id: string;
  mandate_id: string;
  agent_id: string;
  merchant_id: string;
  merchant_category: string;
  amount: number;
  stated_intent: string;
}): Promise<TransactionEvaluation> {
  const resp = await fetch(`${API_BASE_URL}/transactions/evaluate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data)
  });
  if (!resp.ok) throw new Error("Failed to evaluate transaction");
  return resp.json();
}

export async function fetchTransactions(): Promise<TransactionSummary[]> {
  const resp = await fetch(`${API_BASE_URL}/transactions`);
  if (!resp.ok) throw new Error("Failed to fetch transactions");
  return resp.json();
}

export async function approveStepUp(transactionId: string, userId: string) {
  const resp = await fetch(`${API_BASE_URL}/transactions/${transactionId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId })
  });
  if (!resp.ok) throw new Error("Failed to approve step-up");
  return resp.json();
}

export async function rejectStepUp(transactionId: string, userId: string) {
  const resp = await fetch(`${API_BASE_URL}/transactions/${transactionId}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId })
  });
  if (!resp.ok) throw new Error("Failed to reject step-up");
  return resp.json();
}

export async function fetchAuditLogs(transactionId: string): Promise<AuditLogItem[]> {
  const resp = await fetch(`${API_BASE_URL}/audit/${transactionId}`);
  if (!resp.ok) throw new Error("Failed to fetch audit logs");
  return resp.json();
}

export async function runSimulationBenchmark(): Promise<MetricsResponse> {
  const resp = await fetch(`${API_BASE_URL}/simulation/run`, {
    method: "POST"
  });
  if (!resp.ok) throw new Error("Failed to run simulation benchmark");
  return resp.json();
}

export async function runRedTeamAttacks(mandateId?: string): Promise<RedTeamSummary> {
  const url = mandateId ? `${API_BASE_URL}/red-team/run?mandate_id=${mandateId}` : `${API_BASE_URL}/red-team/run`;
  const resp = await fetch(url, { method: "POST" });
  if (!resp.ok) throw new Error("Failed to run red team attacks");
  return resp.json();
}

export async function fetchAgentReplay(agentId: string = "agent_001"): Promise<AgentReplayResponse> {
  const resp = await fetch(`${API_BASE_URL}/agents/${agentId}/replay`);
  if (!resp.ok) throw new Error("Failed to fetch agent replay");
  return resp.json();
}
