import React, { useState, useEffect } from 'react';
import {
  ShieldCheck, Play, RotateCcw, AlertTriangle,
  CheckCircle2, XCircle, Clock, Zap, FileText, BarChart3, Plus, Ban,
  Swords, History, HelpCircle
} from 'lucide-react';
import type { Mandate, TransactionSummary, MetricsResponse, AuditLogItem, RedTeamSummary, AgentReplayResponse } from './api';
import {
  fetchMandates, createMandate, revokeMandate, evaluateTransaction,
  fetchTransactions, approveStepUp, rejectStepUp, fetchAuditLogs,
  runSimulationBenchmark, runRedTeamAttacks, fetchAgentReplay
} from './api';


export default function App() {
  const [activeTab, setActiveTab] = useState<'feed' | 'mandates' | 'stepup' | 'redteam' | 'agentreplay' | 'audit' | 'metrics'>('feed');

  // Data state
  const [mandates, setMandates] = useState<Mandate[]>([]);
  const [transactions, setTransactions] = useState<TransactionSummary[]>([]);
  const [selectedTxnId, setSelectedTxnId] = useState<string | null>(null);
  const [auditLogs, setAuditLogs] = useState<AuditLogItem[]>([]);
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [redTeamSummary, setRedTeamSummary] = useState<RedTeamSummary | null>(null);
  const [agentReplay, setAgentReplay] = useState<AgentReplayResponse | null>(null);

  // Form & UI states
  const [loading, setLoading] = useState<boolean>(false);
  const [evaluating, setEvaluating] = useState<boolean>(false);
  const [runningRedTeam, setRunningRedTeam] = useState<boolean>(false);
  const [loadingReplay, setLoadingReplay] = useState<boolean>(false);
  const [bannerMsg, setBannerMsg] = useState<string | null>(null);

  // Mandate form
  const [promptText, setPromptText] = useState("Buy groceries for my family every week, up to ₹3,000");
  const [totalLimit, setTotalLimit] = useState(12000);
  const [perTxLimit, setPerTxLimit] = useState(3000);
  const [selectedCats, setSelectedCats] = useState<string[]>(["grocery"]);

  useEffect(() => {
    loadInitialData();
  }, []);

  const loadInitialData = async () => {
    setLoading(true);
    try {
      const [mList, tList, mResp] = await Promise.all([
        fetchMandates(),
        fetchTransactions(),
        runSimulationBenchmark()
      ]);
      setMandates(mList);
      setTransactions(tList);
      setMetrics(mResp);
      if (tList.length > 0) {
        setSelectedTxnId(tList[0].transaction_id);
      }
    } catch (err) {
      console.error(err);
      showBanner("Error connecting to DIV Backend Server. Ensure uvicorn main:app is running on port 8000.");
    } finally {
      setLoading(false);
    }
  };

  const showBanner = (msg: string) => {
    setBannerMsg(msg);
    setTimeout(() => setBannerMsg(null), 5000);
  };

  const handleCreateMandate = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setLoading(true);
      const newM = await createMandate({
        user_id: "user_001",
        raw_text: promptText,
        total_limit: totalLimit,
        per_transaction_limit: perTxLimit,
        allowed_categories: selectedCats,
        excluded_categories: ["electronics", "gambling"]
      });
      showBanner(`Mandate created successfully! ID: ${newM.mandate_id}`);
      const mList = await fetchMandates();
      setMandates(mList);
    } catch (err: any) {
      showBanner(`Failed to create mandate: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleRevokeMandate = async (id: string) => {
    try {
      await revokeMandate(id);
      showBanner(`Mandate ${id} revoked.`);
      const mList = await fetchMandates();
      setMandates(mList);
    } catch (err: any) {
      showBanner(`Failed to revoke mandate: ${err.message}`);
    }
  };

  const handleSimulateAgentTxn = async (scenario: 'normal' | 'large_stockup' | 'duplicate' | 'excluded_cat') => {
    if (mandates.length === 0) {
      showBanner("Please create an active mandate first!");
      return;
    }
    const targetMandate = mandates[0];

    try {
      setEvaluating(true);
      let payload;

      if (scenario === 'normal') {
        payload = {
          idempotency_key: `idemp_${Date.now()}`,
          user_id: targetMandate.user_id,
          mandate_id: targetMandate.mandate_id,
          agent_id: "agent_grocery_bot",
          merchant_id: "m_bigbasket",
          merchant_category: "grocery",
          amount: 850.0,
          stated_intent: "weekly fresh produce & milk refill"
        };
      } else if (scenario === 'duplicate') {
        payload = {
          idempotency_key: `idemp_${Date.now()}`,
          user_id: targetMandate.user_id,
          mandate_id: targetMandate.mandate_id,
          agent_id: "agent_grocery_bot",
          merchant_id: "m_bigbasket",
          merchant_category: "grocery",
          amount: 850.0,
          stated_intent: "weekly fresh produce & milk refill"
        };
      } else if (scenario === 'large_stockup') {
        payload = {
          idempotency_key: `idemp_${Date.now()}`,
          user_id: targetMandate.user_id,
          mandate_id: targetMandate.mandate_id,
          agent_id: "agent_grocery_bot",
          merchant_id: "m_nature_basket",
          merchant_category: "grocery",
          amount: 2850.0,
          stated_intent: "bulk pantry stock-up before long vacation trip"
        };
      } else {
        payload = {
          idempotency_key: `idemp_${Date.now()}`,
          user_id: targetMandate.user_id,
          mandate_id: targetMandate.mandate_id,
          agent_id: "agent_grocery_bot",
          merchant_id: "m_croma",
          merchant_category: "electronics",
          amount: 1500.0,
          stated_intent: "buy smart home hub speaker"
        };
      }

      const evalRes = await evaluateTransaction(payload);
      showBanner(`Evaluated: ${evalRes.final_decision} (Score ${evalRes.intent_fit_score}/100)`);

      const tList = await fetchTransactions();
      setTransactions(tList);
      setSelectedTxnId(evalRes.transaction_id);
    } catch (err: any) {
      showBanner(`Simulation failed: ${err.message}`);
    } finally {
      setEvaluating(false);
    }
  };

  const handleApproveStepUp = async (transactionId: string) => {
    try {
      const txn = transactions.find(t => t.transaction_id === transactionId);
      const uId = txn?.user_id || "user_001";
      await approveStepUp(transactionId, uId);
      showBanner(`Transaction ${transactionId} APPROVED by user! Payment executed.`);
      const tList = await fetchTransactions();
      setTransactions(tList);
    } catch (err: any) {
      showBanner(`Approval failed: ${err.message}`);
    }
  };

  const handleRejectStepUp = async (transactionId: string) => {
    try {
      const txn = transactions.find(t => t.transaction_id === transactionId);
      const uId = txn?.user_id || "user_001";
      await rejectStepUp(transactionId, uId);
      showBanner(`Transaction ${transactionId} REJECTED by user! Cancelled.`);
      const tList = await fetchTransactions();
      setTransactions(tList);
    } catch (err: any) {
      showBanner(`Rejection failed: ${err.message}`);
    }
  };


  const handleRunBenchmark = async () => {
    try {
      setLoading(true);
      const res = await runSimulationBenchmark();
      setMetrics(res);
      showBanner(`Benchmark simulation replayed across ${res.total_evaluated} test cases! Dynamic metrics updated.`);
    } catch (err: any) {
      showBanner(`Benchmark run failed: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleRunRedTeam = async () => {
    setRunningRedTeam(true);
    try {
      const summary = await runRedTeamAttacks();
      setRedTeamSummary(summary);
      showBanner(`Red-Team attack evaluation completed: ${summary.attacks_run} attacks tested across pipeline.`);
    } catch (err: any) {
      showBanner(`Red-Team run failed: ${err.message}`);
    } finally {
      setRunningRedTeam(false);
    }
  };

  const handleLoadAgentReplay = async () => {
    setLoadingReplay(true);
    try {
      const replay = await fetchAgentReplay("agent_001");
      setAgentReplay(replay);
    } catch (err: any) {
      showBanner(`Agent replay load failed: ${err.message}`);
    } finally {
      setLoadingReplay(false);
    }
  };

  useEffect(() => {
    if (selectedTxnId && activeTab === 'audit') {
      fetchAuditLogs(selectedTxnId)
        .then(setAuditLogs)
        .catch(() => setAuditLogs([]));
    }
  }, [selectedTxnId, activeTab]);

  useEffect(() => {
    if (activeTab === 'redteam' && !redTeamSummary) {
      handleRunRedTeam();
    }
    if (activeTab === 'agentreplay' && !agentReplay) {
      handleLoadAgentReplay();
    }
  }, [activeTab]);

  const selectedTxn = transactions.find(t => t.transaction_id === selectedTxnId) || transactions[0];
  const pendingStepUps = transactions.filter(t => t.state === 'STEP_UP_REQUIRED');
  const activeMandate = mandates.find(m => m.status === 'ACTIVE') || mandates[0];

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      {/* Top Banner Message */}
      {bannerMsg && (
        <div style={{
          position: 'fixed', top: '16px', right: '16px', zIndex: 1000,
          background: 'rgba(30, 41, 59, 0.95)', border: '1px solid var(--accent-primary)',
          borderRadius: 'var(--radius-md)', padding: '12px 20px', color: '#fff',
          boxShadow: 'var(--shadow-main)', display: 'flex', alignItems: 'center', gap: '10px'
        }}>
          <Zap size={18} color="#6366f1" />
          <span style={{ fontSize: '0.9rem', fontWeight: 500 }}>{bannerMsg}</span>
        </div>
      )}

      {/* Navigation Header */}
      <header style={{
        background: 'var(--bg-secondary)', borderBottom: '1px solid var(--border-color)',
        padding: '16px 32px', display: 'flex', alignItems: 'center', justifyContent: 'space-between'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{
            width: '40px', height: '40px', borderRadius: '12px',
            background: 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: 'var(--shadow-glow)'
          }}>
            <ShieldCheck color="#fff" size={24} />
          </div>
          <div>
            <h1 style={{ fontSize: '1.25rem', color: '#fff' }}>Delegated Intent Verifier (DIV)</h1>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Razorpay AI Risk Manager | Agentic Payment Trust Layer</p>
          </div>
        </div>

        {/* Tab Switcher */}
        <nav style={{ display: 'flex', gap: '6px', background: 'rgba(255, 255, 255, 0.03)', padding: '4px', borderRadius: '12px' }}>
          <button onClick={() => setActiveTab('feed')} className={`btn ${activeTab === 'feed' ? 'btn-primary' : 'btn-secondary'}`} style={{ padding: '8px 14px', fontSize: '0.82rem' }}>
            <Zap size={15} /> Live Feed
          </button>
          <button onClick={() => setActiveTab('mandates')} className={`btn ${activeTab === 'mandates' ? 'btn-primary' : 'btn-secondary'}`} style={{ padding: '8px 14px', fontSize: '0.82rem' }}>
            <FileText size={15} /> Mandates
          </button>
          <button onClick={() => setActiveTab('stepup')} className={`btn ${activeTab === 'stepup' ? 'btn-primary' : 'btn-secondary'}`} style={{ padding: '8px 14px', fontSize: '0.82rem', position: 'relative' }}>
            <AlertTriangle size={15} /> Step-Up Hub
            {pendingStepUps.length > 0 && (
              <span style={{
                position: 'absolute', top: '-4px', right: '-4px', background: 'var(--status-yellow)',
                color: '#000', borderRadius: '50%', width: '18px', height: '18px', fontSize: '0.7rem',
                fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center'
              }}>{pendingStepUps.length}</span>
            )}
          </button>
          <button onClick={() => setActiveTab('redteam')} className={`btn ${activeTab === 'redteam' ? 'btn-primary' : 'btn-secondary'}`} style={{ padding: '8px 14px', fontSize: '0.82rem' }}>
            <Swords size={15} color="var(--status-red)" /> Red-Team
          </button>
          <button onClick={() => setActiveTab('agentreplay')} className={`btn ${activeTab === 'agentreplay' ? 'btn-primary' : 'btn-secondary'}`} style={{ padding: '8px 14px', fontSize: '0.82rem' }}>
            <History size={15} color="var(--accent-primary)" /> Agent Behaviour
          </button>
          <button onClick={() => setActiveTab('audit')} className={`btn ${activeTab === 'audit' ? 'btn-primary' : 'btn-secondary'}`} style={{ padding: '8px 14px', fontSize: '0.82rem' }}>
            <Clock size={15} /> Audit Trail
          </button>
          <button onClick={() => setActiveTab('metrics')} className={`btn ${activeTab === 'metrics' ? 'btn-primary' : 'btn-secondary'}`} style={{ padding: '8px 14px', fontSize: '0.82rem' }}>
            <BarChart3 size={15} /> Benchmark
          </button>
        </nav>
      </header>

      {/* Main Content Area */}
      <main style={{ flex: 1, padding: '32px', maxWidth: '1400px', margin: '0 auto', width: '100%' }}>

        {/* ========================================================================= */}
        {/* TAB 1: LIVE FEED & INTENT-FIT INSPECTOR */}
        {/* ========================================================================= */}
        {activeTab === 'feed' && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
            {/* Left Column: Agent Simulator & Feed */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
              {/* Simulator Action Panel */}
              <div className="glass-card">
                <h3 style={{ fontSize: '1rem', color: 'var(--text-secondary)', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Play size={18} color="var(--accent-primary)" /> Simulate AI Agent Purchase Request
                </h3>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                  <button onClick={() => handleSimulateAgentTxn('normal')} disabled={evaluating} className="btn btn-secondary" style={{ justifyContent: 'flex-start' }}>
                    <CheckCircle2 size={16} color="var(--status-green)" /> 1. Typical Grocery (Auto Approve)
                  </button>
                  <button onClick={() => handleSimulateAgentTxn('duplicate')} disabled={evaluating} className="btn btn-secondary" style={{ justifyContent: 'flex-start' }}>
                    <Ban size={16} color="var(--status-red)" /> 2. Repeat Txn within 5s (Duplicate)
                  </button>
                  <button onClick={() => handleSimulateAgentTxn('large_stockup')} disabled={evaluating} className="btn btn-secondary" style={{ justifyContent: 'flex-start' }}>
                    <AlertTriangle size={16} color="var(--status-yellow)" /> 3. Off-Pattern Stockup (Step-Up)
                  </button>
                  <button onClick={() => handleSimulateAgentTxn('excluded_cat')} disabled={evaluating} className="btn btn-secondary" style={{ justifyContent: 'flex-start' }}>
                    <XCircle size={16} color="var(--status-red)" /> 4. Excluded Category (Hard Block)
                  </button>
                </div>
              </div>

              {/* Transactions Live Stream */}
              <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <h3 style={{ fontSize: '1.1rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <Zap size={18} color="var(--accent-primary)" /> Transaction Evaluation Feed
                </h3>
                {transactions.length === 0 ? (
                  <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>No evaluation records found. Use the buttons above to trigger a transaction.</p>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    {transactions.map(t => (
                      <div
                        key={t.transaction_id}
                        onClick={() => setSelectedTxnId(t.transaction_id)}
                        className="glass-card"
                        style={{
                          padding: '16px', cursor: 'pointer',
                          borderColor: selectedTxnId === t.transaction_id ? 'var(--accent-primary)' : 'var(--border-color)',
                          background: selectedTxnId === t.transaction_id ? 'rgba(99, 102, 241, 0.08)' : 'rgba(255,255,255,0.02)'
                        }}
                      >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
                          <div>
                            <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{new Date(t.timestamp).toLocaleTimeString()}</span>
                            <h4 style={{ fontSize: '1.1rem', color: '#fff', margin: '2px 0' }}>₹{t.amount.toFixed(2)}</h4>
                            <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Merchant: {t.merchant_id} ({t.merchant_category})</span>
                          </div>
                          <div style={{ textAlign: 'right' }}>
                            <span className={`badge badge-${t.final_decision === 'APPROVE' ? 'approved' : t.final_decision === 'STEP_UP' ? 'stepup' : 'blocked'}`}>
                              {t.final_decision === 'APPROVE' ? 'AUTO APPROVE' : t.final_decision === 'STEP_UP' ? 'STEP_UP_REQUIRED' : 'HARD BLOCK'}
                            </span>
                            <p style={{ fontSize: '0.85rem', fontWeight: 700, color: '#fff', marginTop: '6px' }}>
                              Score: {t.intent_fit_score.toFixed(1)}/100
                            </p>
                          </div>
                        </div>
                        <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>
                          Stated Intent: "{t.stated_intent}"
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Right Column: FEATURE 3 DECISION EXPLAINABILITY PANEL */}
            <div className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
              <h3 style={{ fontSize: '1.1rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <HelpCircle size={20} color="var(--accent-primary)" /> WHY DID DIV MAKE THIS DECISION?
              </h3>

              {selectedTxn ? (
                <>
                  {/* User Intent Context */}
                  <div style={{ background: 'rgba(0,0,0,0.3)', padding: '14px', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                    <span style={{ fontSize: '0.75rem', color: 'var(--accent-primary)', fontWeight: 700, textTransform: 'uppercase' }}>
                      1. Delegated User Intent
                    </span>
                    <p style={{ fontSize: '0.9rem', color: '#fff', marginTop: '4px', fontWeight: 500 }}>
                      "{activeMandate?.raw_text || 'Weekly grocery shopping up to ₹3,000'}"
                    </p>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      Total Limit: ₹{activeMandate?.total_limit || 12000} | Remaining: ₹{activeMandate?.remaining_limit || 9500}
                    </span>
                  </div>

                  {/* Hard Safety Checks */}
                  <div style={{ background: 'rgba(0,0,0,0.3)', padding: '14px', borderRadius: '8px', border: '1px solid var(--border-color)' }}>
                    <span style={{ fontSize: '0.75rem', color: 'var(--status-green)', fontWeight: 700, textTransform: 'uppercase' }}>
                      2. Deterministic Safety Checks (Pre-Scoring)
                    </span>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginTop: '8px', fontSize: '0.8rem' }}>
                      <span style={{ color: 'var(--status-green)' }}>✓ Mandate Active</span>
                      <span style={{ color: 'var(--status-green)' }}>✓ Budget Remaining</span>
                      <span style={{ color: selectedTxn.merchant_category === 'electronics' ? 'var(--status-red)' : 'var(--status-green)' }}>
                        {selectedTxn.merchant_category === 'electronics' ? '✗ Category Excluded' : '✓ Category Authorized'}
                      </span>
                      <span style={{ color: selectedTxn.ai_explanation_text.includes('duplicate') ? 'var(--status-red)' : 'var(--status-green)' }}>
                        {selectedTxn.ai_explanation_text.includes('duplicate') ? '✗ Duplicate (within 5s)' : '✓ Velocity Acceptable'}
                      </span>
                    </div>
                  </div>

                  {/* 7 Score Component Bars */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 700, textTransform: 'uppercase' }}>
                      3. Intent-Fit Scoring Signals (Weighted 0-100)
                    </span>

                    {[
                      { label: 'Category Match', score: selectedTxn.score_breakdown.category_match || 0, max: 20, color: '#6366f1' },
                      { label: 'Amount Deviation', score: selectedTxn.score_breakdown.amount_deviation || 0, max: 25, color: '#10b981' },
                      { label: 'Frequency Deviation', score: selectedTxn.score_breakdown.frequency_deviation || 0, max: 15, color: '#3b82f6' },
                      { label: 'Merchant Familiarity', score: selectedTxn.score_breakdown.merchant_familiarity || 0, max: 15, color: '#ec4899' },
                      { label: 'Time Pattern Fit', score: selectedTxn.score_breakdown.time_pattern_fit || 0, max: 5, color: '#8b5cf6' },
                      { label: 'Velocity Proximity (Soft)', score: selectedTxn.score_breakdown.velocity_proximity || 0, max: 10, color: '#f59e0b' },
                      { label: 'Intent Similarity (LLM)', score: selectedTxn.score_breakdown.intent_similarity || 0, max: 10, color: '#14b8a6' },
                    ].map((comp, i) => (
                      <div key={i}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', marginBottom: '4px' }}>
                          <span style={{ color: 'var(--text-secondary)' }}>{comp.label}</span>
                          <span style={{ fontWeight: 600, color: '#fff' }}>{comp.score} / {comp.max} pts</span>
                        </div>
                        <div className="progress-bar-bg">
                          <div className="progress-bar-fill" style={{ width: `${(comp.score / comp.max) * 100}%`, background: comp.color }} />
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* Decision & Concise Rationale */}
                  <div style={{ background: 'rgba(0,0,0,0.4)', padding: '16px', borderRadius: '8px', borderLeft: `4px solid ${selectedTxn.final_decision === 'APPROVE' ? 'var(--status-green)' : selectedTxn.final_decision === 'STEP_UP' ? 'var(--status-yellow)' : 'var(--status-red)'}` }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                      <span style={{ fontWeight: 700, color: '#fff', fontSize: '0.95rem' }}>Final Policy Decision</span>
                      <span className={`badge badge-${selectedTxn.final_decision === 'APPROVE' ? 'approved' : selectedTxn.final_decision === 'STEP_UP' ? 'stepup' : 'blocked'}`}>
                        {selectedTxn.final_decision === 'APPROVE' ? '🟢 AUTO APPROVED' : selectedTxn.final_decision === 'STEP_UP' ? '🟡 STEP_UP_REQUIRED' : '🔴 HARD BLOCK'}
                      </span>
                    </div>
                    <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                      <strong>Why?</strong> {selectedTxn.ai_explanation_text || "Standard evaluation completed."}
                    </p>
                  </div>
                </>
              ) : (
                <p style={{ color: 'var(--text-muted)' }}>Select a transaction from the feed to inspect details.</p>
              )}
            </div>
          </div>
        )}

        {/* ========================================================================= */}
        {/* TAB 2: MANDATES & STRUCTURED INTENT */}
        {/* ========================================================================= */}
        {activeTab === 'mandates' && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
            {/* Create Mandate Form */}
            <div className="glass-card">
              <h3 style={{ fontSize: '1.1rem', color: '#fff', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Plus size={20} color="var(--accent-primary)" /> Create Spending Mandate (Natural Language + Limits)
              </h3>
              <form onSubmit={handleCreateMandate} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div>
                  <label style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', display: 'block', marginBottom: '6px' }}>
                    Natural Language Delegation Prompt (LLM Extracts Intent Profile)
                  </label>
                  <textarea
                    rows={3}
                    value={promptText}
                    onChange={(e) => setPromptText(e.target.value)}
                    placeholder="e.g. You can buy groceries for my family every week up to ₹3,000"
                    required
                  />
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                  <div>
                    <label style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', display: 'block', marginBottom: '6px' }}>Total Mandate Budget (₹)</label>
                    <input type="number" value={totalLimit} onChange={(e) => setTotalLimit(Number(e.target.value))} required />
                  </div>
                  <div>
                    <label style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', display: 'block', marginBottom: '6px' }}>Per-Tx Limit Cap (₹)</label>
                    <input type="number" value={perTxLimit} onChange={(e) => setPerTxLimit(Number(e.target.value))} required />
                  </div>
                </div>
                <div>
                  <label style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', display: 'block', marginBottom: '6px' }}>Allowed Category Tags</label>
                  <div style={{ display: 'flex', gap: '12px' }}>
                    {['grocery', 'food_delivery', 'travel', 'utilities'].map(cat => (
                      <label key={cat} style={{ fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                        <input
                          type="checkbox"
                          checked={selectedCats.includes(cat)}
                          onChange={(e) => {
                            if (e.target.checked) setSelectedCats([...selectedCats, cat]);
                            else setSelectedCats(selectedCats.filter(c => c !== cat));
                          }}
                        /> {cat}
                      </label>
                    ))}
                  </div>
                </div>
                <button type="submit" disabled={loading} className="btn btn-primary" style={{ marginTop: '8px' }}>
                  Create Mandate & Extract Intent
                </button>
              </form>
            </div>

            {/* Mandates & Intent Profiles List */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <h3 style={{ fontSize: '1.1rem', color: '#fff' }}>Active Mandates & LLM-Extracted Intent Profiles</h3>
              {mandates.map(m => (
                <div key={m.mandate_id} className="glass-card" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Mandate ID: {m.mandate_id}</span>
                      <h4 style={{ fontSize: '1rem', color: '#fff', marginTop: '2px' }}>"{m.raw_text}"</h4>
                    </div>
                    <span className={`badge badge-${m.status === 'ACTIVE' ? 'approved' : 'blocked'}`}>{m.status}</span>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                    <div>Total Limit: <strong>₹{m.total_limit.toFixed(2)}</strong></div>
                    <div>Remaining: <strong>₹{m.remaining_limit.toFixed(2)}</strong></div>
                    <div>Allowed: <strong>{m.allowed_categories.join(', ')}</strong></div>
                    <div>Excluded: <strong>{m.excluded_categories.join(', ')}</strong></div>
                  </div>

                  {m.intent_profile && (
                    <div style={{ borderTop: '1px solid var(--border-color)', paddingTop: '12px', marginTop: '12px' }}>
                      <h5 style={{ fontSize: '0.8rem', color: 'var(--accent-primary)', marginBottom: '4px' }}>Extracted Intent Profile</h5>
                      <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}><strong>Purpose:</strong> {m.intent_profile.purpose}</p>
                      <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}><strong>Expected Amount Range:</strong> ₹{m.intent_profile.expected_amount_range[0]} - ₹{m.intent_profile.expected_amount_range[1]}</p>
                    </div>
                  )}

                  {m.status === 'ACTIVE' && (
                    <button onClick={() => handleRevokeMandate(m.mandate_id)} className="btn btn-secondary" style={{ color: 'var(--status-red)', borderColor: 'var(--status-red-border)', alignSelf: 'flex-end' }}>
                      Revoke Mandate
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ========================================================================= */}
        {/* TAB 3: STEP-UP CONFIRMATION HUB */}
        {/* ========================================================================= */}
        {activeTab === 'stepup' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <div>
              <h2 style={{ fontSize: '1.4rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '10px' }}>
                <AlertTriangle color="var(--status-yellow)" size={24} /> Human-in-the-Loop Step-Up Confirmation Hub
              </h2>
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginTop: '4px' }}>
                Transactions scoring 45-74 are held in <code>STEP_UP_REQUIRED</code> state. Funds do not move until explicit user confirmation.
              </p>
            </div>

            {pendingStepUps.length === 0 ? (
              <div className="glass-card" style={{ textAlign: 'center', padding: '48px' }}>
                <CheckCircle2 color="var(--status-green)" size={48} style={{ margin: '0 auto 16px', opacity: 0.8 }} />
                <h3 style={{ fontSize: '1.2rem', color: '#fff' }}>No Pending Step-Up Requests</h3>
                <p style={{ color: 'var(--text-muted)', fontSize: '0.9rem', marginTop: '8px' }}>
                  All agent payment requests are either auto-approved or hard-blocked.
                </p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                {pendingStepUps.map(t => (
                  <div key={t.transaction_id} className="glass-card" style={{ borderColor: 'var(--status-yellow-border)', background: 'rgba(245, 158, 11, 0.03)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px' }}>
                      <div>
                        <span className="badge badge-stepup" style={{ marginBottom: '8px' }}>STEP_UP_REQUIRED</span>
                        <h3 style={{ fontSize: '1.5rem', color: '#fff' }}>₹{t.amount.toFixed(2)} at {t.merchant_id}</h3>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>Stated Intent: "{t.stated_intent}"</p>
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Score: {t.intent_fit_score.toFixed(1)}/100</span>
                      </div>
                    </div>

                    <div style={{ background: 'rgba(0,0,0,0.3)', padding: '12px', borderRadius: '6px', marginBottom: '16px', border: '1px solid var(--border-color)' }}>
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Why Step-Up was triggered:</span>
                      <p style={{ fontSize: '0.85rem', color: '#fff', marginTop: '2px' }}>{t.ai_explanation_text}</p>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                      <button onClick={() => handleApproveStepUp(t.transaction_id)} className="btn btn-primary" style={{ background: 'var(--status-green)', color: '#000', fontWeight: 700 }}>
                        <CheckCircle2 size={18} /> Approve & Execute Payment
                      </button>
                      <button onClick={() => handleRejectStepUp(t.transaction_id)} className="btn btn-secondary" style={{ color: 'var(--status-red)', borderColor: 'var(--status-red-border)', fontWeight: 700 }}>
                        <XCircle size={18} /> Reject & Cancel
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ========================================================================= */}
        {/* TAB 4: FEATURE 1 — AGENT RED-TEAM / ATTACK SIMULATOR */}
        {/* ========================================================================= */}
        {activeTab === 'redteam' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h2 style={{ fontSize: '1.4rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <Swords size={26} color="var(--status-red)" /> ⚔️ Agent Red-Team / Attack Simulator
                </h2>
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginTop: '4px' }}>
                  Intentionally attack the AI Agent pipeline to verify that DIV enforces hard safety boundaries and contains misaligned behavior.
                </p>
              </div>
              <button onClick={handleRunRedTeam} disabled={runningRedTeam} className="btn btn-primary" style={{ padding: '10px 20px', background: 'linear-gradient(135deg, #ef4444 0%, #dc2626 100%)' }}>
                <Play size={16} /> {runningRedTeam ? 'Running Attacks...' : '⚔️ Run All Attacks'}
              </button>
            </div>

            {redTeamSummary && (
              <>
                {/* 5 Dynamic Summary Metric Cards */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '16px' }}>
                  <div className="glass-card">
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Attacks Run</span>
                    <h4 style={{ fontSize: '1.6rem', color: '#fff' }}>{redTeamSummary.attacks_run}</h4>
                  </div>
                  <div className="glass-card">
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Blocked</span>
                    <h4 style={{ fontSize: '1.6rem', color: 'var(--status-red)' }}>{redTeamSummary.blocked}</h4>
                  </div>
                  <div className="glass-card">
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Step-Up Required</span>
                    <h4 style={{ fontSize: '1.6rem', color: 'var(--status-yellow)' }}>{redTeamSummary.step_up}</h4>
                  </div>
                  <div className="glass-card">
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Auto Approved</span>
                    <h4 style={{ fontSize: '1.6rem', color: 'var(--status-green)' }}>{redTeamSummary.approved}</h4>
                  </div>
                  <div className="glass-card" style={{ borderColor: redTeamSummary.unsafe_actions === 0 ? 'var(--status-green-border)' : 'var(--status-red-border)' }}>
                    <span style={{ fontSize: '0.75rem', color: redTeamSummary.unsafe_actions === 0 ? 'var(--status-green)' : 'var(--status-red)' }}>Unsafe Actions</span>
                    <h4 style={{ fontSize: '1.6rem', color: redTeamSummary.unsafe_actions === 0 ? 'var(--status-green)' : 'var(--status-red)' }}>{redTeamSummary.unsafe_actions}</h4>
                  </div>
                </div>

                {/* Results Table */}
                <div className="glass-card" style={{ padding: 0, overflow: 'hidden' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.88rem' }}>
                    <thead>
                      <tr style={{ background: 'rgba(255,255,255,0.04)', borderBottom: '1px solid var(--border-color)' }}>
                        <th style={{ padding: '14px 18px', textAlign: 'left', color: 'var(--text-muted)' }}>Attack Name</th>
                        <th style={{ padding: '14px 18px', textAlign: 'left', color: 'var(--text-muted)' }}>Transaction</th>
                        <th style={{ padding: '14px 18px', textAlign: 'left', color: 'var(--text-muted)' }}>Decision</th>
                        <th style={{ padding: '14px 18px', textAlign: 'left', color: 'var(--text-muted)' }}>Score</th>
                        <th style={{ padding: '14px 18px', textAlign: 'left', color: 'var(--text-muted)' }}>Rule Triggered</th>
                        <th style={{ padding: '14px 18px', textAlign: 'left', color: 'var(--text-muted)' }}>Reason</th>
                      </tr>
                    </thead>
                    <tbody>
                      {redTeamSummary.results.map((r, i) => (
                        <tr key={i} style={{ borderBottom: '1px solid var(--border-color)' }}>
                          <td style={{ padding: '14px 18px', fontWeight: 600, color: '#fff' }}>{r.attack_name}</td>
                          <td style={{ padding: '14px 18px', color: 'var(--text-secondary)' }}>{r.transaction_description}</td>
                          <td style={{ padding: '14px 18px' }}>
                            <span className={`badge badge-${r.decision === 'BLOCK' || r.decision === 'REJECTED' ? 'blocked' : r.decision === 'STEP_UP' ? 'stepup' : 'approved'}`}>
                              {r.decision}
                            </span>
                          </td>
                          <td style={{ padding: '14px 18px', fontWeight: 700, color: '#fff' }}>{r.intent_fit_score.toFixed(1)}/100</td>
                          <td style={{ padding: '14px 18px', color: 'var(--status-red)', fontFamily: 'monospace', fontSize: '0.8rem' }}>{r.hard_rule_triggered || 'None'}</td>
                          <td style={{ padding: '14px 18px', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>{r.reason}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontStyle: 'italic', textAlign: 'center' }}>
                  {redTeamSummary.disclaimer}
                </p>
              </>
            )}
          </div>
        )}

        {/* ========================================================================= */}
        {/* TAB 5: FEATURE 2 — AGENT BEHAVIOUR REPLAY & TIMELINE */}
        {/* ========================================================================= */}
        {activeTab === 'agentreplay' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h2 style={{ fontSize: '1.4rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <History size={26} color="var(--accent-primary)" /> 🤖 Agent Behaviour Replay & Timeline
                </h2>
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginTop: '4px' }}>
                  Observe how AI Agents execute transactions over time and verify whether their actions remain aligned with delegated intent.
                </p>
              </div>
              <button onClick={handleLoadAgentReplay} disabled={loadingReplay} className="btn btn-primary">
                <RotateCcw size={16} /> Load Agent Replay
              </button>
            </div>

            {agentReplay && (
              <>
                <div className="glass-card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Target Agent ID: {agentReplay.agent_id}</span>
                    <h3 style={{ fontSize: '1.2rem', color: '#fff', marginTop: '2px' }}>"{agentReplay.mandate_summary}"</h3>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block' }}>Behaviour Consistency</span>
                    <span className={`badge badge-${agentReplay.behaviour_consistency === 'HIGH' ? 'approved' : agentReplay.behaviour_consistency === 'MODERATE' ? 'stepup' : 'blocked'}`} style={{ fontSize: '0.9rem', padding: '6px 14px' }}>
                      {agentReplay.behaviour_consistency} CONSISTENCY
                    </span>
                  </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '16px' }}>
                  <div className="glass-card"><span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Total Txns</span><h4 style={{ fontSize: '1.4rem', color: '#fff' }}>{agentReplay.total_transactions}</h4></div>
                  <div className="glass-card"><span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Approved</span><h4 style={{ fontSize: '1.4rem', color: 'var(--status-green)' }}>{agentReplay.approved_count}</h4></div>
                  <div className="glass-card"><span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Step-Up</span><h4 style={{ fontSize: '1.4rem', color: 'var(--status-yellow)' }}>{agentReplay.step_up_count}</h4></div>
                  <div className="glass-card"><span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Blocked</span><h4 style={{ fontSize: '1.4rem', color: 'var(--status-red)' }}>{agentReplay.blocked_count}</h4></div>
                  <div className="glass-card"><span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Hard Violations</span><h4 style={{ fontSize: '1.4rem', color: 'var(--status-red)' }}>{agentReplay.hard_violations_count}</h4></div>
                </div>

                {/* Timeline List */}
                <div className="glass-card">
                  <h3 style={{ fontSize: '1rem', color: '#fff', marginBottom: '16px' }}>Agent Execution Timeline</h3>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    {agentReplay.timeline.map((item, i) => (
                      <div key={i} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', background: 'rgba(255,255,255,0.02)', borderRadius: '8px', borderLeft: `3px solid ${item.decision === 'APPROVE' ? 'var(--status-green)' : item.decision === 'STEP_UP' ? 'var(--status-yellow)' : 'var(--status-red)'}` }}>
                        <div>
                          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{new Date(item.timestamp).toLocaleTimeString()}</span>
                          <h4 style={{ fontSize: '0.95rem', color: '#fff' }}>₹{item.amount.toFixed(2)} at {item.merchant_id} ({item.merchant_category})</h4>
                          <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>"{item.stated_intent}"</p>
                        </div>
                        <div style={{ textAlign: 'right' }}>
                          <span className={`badge badge-${item.decision === 'APPROVE' ? 'approved' : item.decision === 'STEP_UP' ? 'stepup' : 'blocked'}`}>{item.decision}</span>
                          <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)', display: 'block', marginTop: '4px' }}>Score: {item.intent_fit_score.toFixed(1)}/100</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* ========================================================================= */}
        {/* TAB 6: AUDIT TRAIL INSPECTOR */}
        {/* ========================================================================= */}
        {activeTab === 'audit' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <h2 style={{ fontSize: '1.4rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '10px' }}>
              <Clock color="var(--accent-primary)" size={24} /> Immutable Audit Trail Inspector
            </h2>

            {auditLogs.length > 0 ? (
              <div className="glass-card">
                <h3 style={{ fontSize: '1rem', color: '#fff', marginBottom: '16px' }}>Audit Log Timeline for {selectedTxnId}</h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                  {auditLogs.map((log) => (
                    <div key={log.audit_id} style={{ display: 'flex', gap: '16px', borderLeft: '2px solid var(--accent-primary)', paddingLeft: '16px' }}>
                      <div>
                        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{new Date(log.created_at).toLocaleTimeString()}</span>
                        <h4 style={{ fontSize: '0.95rem', color: 'var(--status-green)' }}>{log.event_type}</h4>
                        <pre style={{
                          background: 'rgba(0,0,0,0.4)', padding: '10px', borderRadius: '6px',
                          fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '6px', overflowX: 'auto'
                        }}>
                          {JSON.stringify(log.payload, null, 2)}
                        </pre>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p style={{ color: 'var(--text-muted)' }}>No audit logs loaded. Select a transaction above.</p>
            )}
          </div>
        )}

        {/* ========================================================================= */}
        {/* TAB 7: DYNAMIC EVALUATION BENCHMARK DASHBOARD */}
        {/* ========================================================================= */}
        {activeTab === 'metrics' && metrics && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h2 style={{ fontSize: '1.4rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <BarChart3 color="var(--accent-primary)" size={24} /> Synthetic Benchmark & Baseline Comparison
                </h2>
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                  Evaluated across synthetic dataset test cases. All metrics are dynamically calculated on replay (no hardcoded values).
                </p>
              </div>
              <button onClick={handleRunBenchmark} disabled={loading} className="btn btn-primary">
                <RotateCcw size={18} /> Run Simulation Benchmark (POST /simulation/run)
              </button>
            </div>

            {/* Headline Safety Metric Card */}
            <div className="glass-card" style={{
              background: 'linear-gradient(135deg, rgba(16, 185, 129, 0.1) 0%, rgba(6, 78, 59, 0.2) 100%)',
              borderColor: 'var(--status-green-border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between'
            }}>
              <div>
                <span style={{ fontSize: '0.85rem', color: 'var(--status-green)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  Headline Safety Invariant
                </span>
                <h3 style={{ fontSize: '2.2rem', color: '#fff', marginTop: '4px' }}>
                  DIV Unsafe-Action Rate: <span style={{ color: 'var(--status-green)' }}>{(metrics.div_metrics.unsafe_action_rate * 100).toFixed(1)}%</span>
                </h3>
              </div>
              <ShieldCheck size={64} color="var(--status-green)" style={{ opacity: 0.8 }} />
            </div>

            {/* Dynamic Comparison Table */}
            <div className="glass-card" style={{ padding: '0', overflow: 'hidden' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.9rem' }}>
                <thead>
                  <tr style={{ background: 'rgba(255, 255, 255, 0.04)', borderBottom: '1px solid var(--border-color)' }}>
                    <th style={{ padding: '16px 20px', color: 'var(--text-muted)' }}>Evaluation Metric</th>
                    <th style={{ padding: '16px 20px', color: 'var(--status-green)', fontWeight: 700 }}>DIV (Agentic Trust Layer)</th>
                    <th style={{ padding: '16px 20px', color: 'var(--text-secondary)' }}>Baseline 1: Static Limit Only</th>
                    <th style={{ padding: '16px 20px', color: 'var(--text-secondary)' }}>Baseline 2: Simple Rules</th>
                  </tr>
                </thead>
                <tbody>
                  <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <td style={{ padding: '14px 20px', fontWeight: 600, color: '#fff' }}>Unsafe-Action Rate (Safety Target: 0%)</td>
                    <td style={{ padding: '14px 20px', color: 'var(--status-green)', fontWeight: 700 }}>{(metrics.div_metrics.unsafe_action_rate * 100).toFixed(1)}%</td>
                    <td style={{ padding: '14px 20px', color: 'var(--status-red)' }}>{(metrics.baseline_1_metrics.unsafe_action_rate * 100).toFixed(1)}%</td>
                    <td style={{ padding: '14px 20px', color: 'var(--status-yellow)' }}>{(metrics.baseline_2_metrics.unsafe_action_rate * 100).toFixed(1)}%</td>
                  </tr>
                  <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <td style={{ padding: '14px 20px', fontWeight: 600, color: '#fff' }}>False Approval Rate</td>
                    <td style={{ padding: '14px 20px', color: 'var(--status-green)', fontWeight: 700 }}>{(metrics.div_metrics.false_approval_rate * 100).toFixed(1)}%</td>
                    <td style={{ padding: '14px 20px', color: 'var(--text-secondary)' }}>{(metrics.baseline_1_metrics.false_approval_rate * 100).toFixed(1)}%</td>
                    <td style={{ padding: '14px 20px', color: 'var(--text-secondary)' }}>{(metrics.baseline_2_metrics.false_approval_rate * 100).toFixed(1)}%</td>
                  </tr>
                  <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <td style={{ padding: '14px 20px', fontWeight: 600, color: '#fff' }}>Precision</td>
                    <td style={{ padding: '14px 20px', color: '#fff', fontWeight: 700 }}>{(metrics.div_metrics.precision * 100).toFixed(1)}%</td>
                    <td style={{ padding: '14px 20px', color: 'var(--text-secondary)' }}>{(metrics.baseline_1_metrics.precision * 100).toFixed(1)}%</td>
                    <td style={{ padding: '14px 20px', color: 'var(--text-secondary)' }}>{(metrics.baseline_2_metrics.precision * 100).toFixed(1)}%</td>
                  </tr>
                  <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <td style={{ padding: '14px 20px', fontWeight: 600, color: '#fff' }}>Recall</td>
                    <td style={{ padding: '14px 20px', color: '#fff', fontWeight: 700 }}>{(metrics.div_metrics.recall * 100).toFixed(1)}%</td>
                    <td style={{ padding: '14px 20px', color: 'var(--text-secondary)' }}>{(metrics.baseline_1_metrics.recall * 100).toFixed(1)}%</td>
                    <td style={{ padding: '14px 20px', color: 'var(--text-secondary)' }}>{(metrics.baseline_2_metrics.recall * 100).toFixed(1)}%</td>
                  </tr>
                  <tr>
                    <td style={{ padding: '14px 20px', fontWeight: 600, color: '#fff' }}>F1 Score</td>
                    <td style={{ padding: '14px 20px', color: 'var(--accent-primary)', fontWeight: 700 }}>{(metrics.div_metrics.f1_score * 100).toFixed(1)}%</td>
                    <td style={{ padding: '14px 20px', color: 'var(--text-secondary)' }}>{(metrics.baseline_1_metrics.f1_score * 100).toFixed(1)}%</td>
                    <td style={{ padding: '14px 20px', color: 'var(--text-secondary)' }}>{(metrics.baseline_2_metrics.f1_score * 100).toFixed(1)}%</td>
                  </tr>
                </tbody>
              </table>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
              <div className="glass-card">
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Total Test Cases Evaluated</span>
                <h4 style={{ fontSize: '1.4rem', color: '#fff' }}>{metrics.total_evaluated} Cases</h4>
              </div>
              <div className="glass-card">
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Average Decision Latency</span>
                <h4 style={{ fontSize: '1.4rem', color: 'var(--accent-primary)' }}>{metrics.avg_latency_ms} ms</h4>
              </div>
            </div>
          </div>
        )}

      </main>
    </div>
  );
}
