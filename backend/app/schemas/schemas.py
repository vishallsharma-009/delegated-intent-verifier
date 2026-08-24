from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


class MandateCreate(BaseModel):
    user_id: str = Field(default="user_001", description="ID of the user creating the mandate")
    raw_text: str = Field(..., description="Natural language prompt describing spending authority")
    total_limit: float = Field(..., gt=0, description="Total budget limit in INR")
    valid_from: Optional[datetime] = Field(default=None, description="Start time of mandate validity")
    valid_to: Optional[datetime] = Field(default=None, description="End time of mandate validity")
    allowed_categories: List[str] = Field(default_factory=list, description="Explicitly allowed categories")
    excluded_categories: List[str] = Field(default_factory=list, description="Explicitly excluded categories")
    per_transaction_limit: Optional[float] = Field(default=None, gt=0, description="Per-transaction cap")
    max_transactions_per_day: Optional[int] = Field(default=None, gt=0, description="Max transactions per day")
    max_transactions_per_week: Optional[int] = Field(default=None, gt=0, description="Max transactions per week")


class IntentProfileSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    intent_id: str
    mandate_id: str
    purpose: str
    allowed_categories: List[str]
    excluded_categories: List[str]
    expected_amount_range: List[float]
    expected_frequency: str
    expected_transactions_per_period: int
    typical_merchant_types: List[str]
    time_pattern: str
    duration: str
    notes: Optional[str] = None


class MandateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    mandate_id: str
    user_id: str
    raw_text: str
    total_limit: float
    remaining_limit: float
    valid_from: datetime
    valid_to: datetime
    allowed_categories: List[str]
    excluded_categories: List[str]
    allowed_merchant_ids: Optional[List[str]] = None
    per_transaction_limit: Optional[float] = None
    max_transactions_per_day: Optional[int] = None
    max_transactions_per_week: Optional[int] = None
    status: str
    created_at: datetime
    revoked_at: Optional[datetime] = None
    intent_profile: Optional[IntentProfileSchema] = None


class TransactionRequest(BaseModel):
    transaction_id: Optional[str] = None
    idempotency_key: str = Field(..., description="Unique client key for duplicate protection")
    user_id: str = Field(..., description="User ID")
    mandate_id: str = Field(..., description="Mandate ID under which transaction is requested")
    agent_id: str = Field(..., description="ID of the AI Agent requesting payment")
    merchant_id: str = Field(..., description="Merchant identifier")
    merchant_category: str = Field(..., description="Category of merchant")
    amount: float = Field(..., gt=0, description="Transaction amount")
    currency: str = Field(default="INR", description="Currency code")
    timestamp: Optional[datetime] = Field(default=None, description="Transaction request timestamp")
    stated_intent: str = Field(..., description="Agent's free text stated purchase intent")
    payment_method: str = Field(default="UPI", description="Payment rail")


class ScoreBreakdown(BaseModel):
    category_match: float = Field(..., description="Weight 20")
    amount_deviation: float = Field(..., description="Weight 25")
    frequency_deviation: float = Field(..., description="Weight 15")
    merchant_familiarity: float = Field(..., description="Weight 15")
    time_pattern_fit: float = Field(..., description="Weight 5")
    velocity_proximity: float = Field(..., description="Weight 10")
    intent_similarity: float = Field(..., description="Weight 10")


class TransactionEvaluationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    transaction_id: str
    idempotency_key: str
    state: str
    final_decision: str  # APPROVE, STEP_UP, BLOCK
    intent_fit_score: float
    score_breakdown: ScoreBreakdown
    hard_rule_triggered: Optional[str] = None
    reason_text: str
    ai_explanation_text: str
    step_up_id: Optional[str] = None
    payment_reference: Optional[str] = None


class StepUpActionRequest(BaseModel):
    user_id: str = Field(..., description="User taking the action")


class StepUpResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    step_up_id: str
    transaction_id: str
    resolution: str  # PENDING, APPROVED, REJECTED, EXPIRED
    created_at: datetime
    expires_at: datetime
    resolved_at: Optional[datetime] = None


class AuditLogSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    audit_id: str
    transaction_id: str
    mandate_id: str
    user_id: str
    agent_id: str
    event_type: str
    payload: Dict[str, Any]
    created_at: datetime


class MetricDetail(BaseModel):
    precision: float
    recall: float
    f1_score: float
    false_approval_rate: float
    false_block_rate: float
    false_step_up_rate: float
    unsafe_action_rate: float


class MetricsResponse(BaseModel):
    div_metrics: MetricDetail
    baseline_1_metrics: MetricDetail  # Static Mandate Limit Only
    baseline_2_metrics: MetricDetail  # Simple Rules
    total_evaluated: int
    avg_latency_ms: float
    evaluated_at: datetime


class RedTeamAttackResult(BaseModel):
    attack_name: str
    transaction_description: str
    decision: str
    intent_fit_score: float
    hard_rule_triggered: Optional[str] = None
    reason: str
    unsafe: bool


class RedTeamSummary(BaseModel):
    attacks_run: int
    blocked: int
    step_up: int
    approved: int
    unsafe_actions: int
    results: List[RedTeamAttackResult]
    disclaimer: str = "Red-Team results are dynamically computed based on synthetic attack scenarios."


class AgentReplayItem(BaseModel):
    transaction_id: str
    timestamp: str
    amount: float
    merchant_id: str = ""
    merchant_category: str

    stated_intent: str
    decision: str
    intent_fit_score: float
    state: str


class AgentReplayResponse(BaseModel):
    agent_id: str
    mandate_id: str
    mandate_summary: str
    total_transactions: int
    approved_count: int
    step_up_count: int
    blocked_count: int
    hard_violations_count: int
    behaviour_consistency: str  # HIGH, MODERATE, LOW
    timeline: List[Dict[str, Any]]
