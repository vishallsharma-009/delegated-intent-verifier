# Delegated Intent Verifier (DIV) — Agentic Payment Trust Layer

**Track:** Razorpay AI Buildathon 2026 — Track 2: AI Risk Manager  
**Positioning:** Agentic Payment Trust Layer for AI-Initiated Payments (Designed for UPI Reserve Pay workflows)  
**Status:** Feature-Complete & Verified (33 Passing Tests, Dynamic Synthetic Evaluation Engine)  

---

## 💡 The Problem

Autonomous AI Agents are increasingly making payments on behalf of users (grocery shopping, travel booking, utility bills). However, traditional financial controls only enforce static dollar limits (`"Can the agent spend this much?"`).

Static caps fail when an agent:
- Fires duplicate purchase requests within seconds due to retry loops.
- Purchases unauthorized items (e.g. ₹2,500 electronics) under a grocery mandate.
- Exceeds spending cadence or deviates from expected purchase patterns.
- Misinterprets user intent while remaining technically within the dollar limit.

## 🛡️ The Solution

The **Delegated Intent Verifier (DIV)** introduces an agentic payment trust layer between AI Agents and payment execution rails.

**DIV** asks: *"Is the agent spending in a way the user actually intended?"*

It evaluates every AI-initiated purchase against:
1. **Natural Language Mandates:** Converted by LLM into structured Intent Profiles.
2. **Deterministic Safety Rules:** Evaluated *before* scoring.
3. **Intent-Fit Scoring Engine:** 7 weighted behavioral and intent alignment signals (0–100).
4. **Policy Decision Engine:**
   - **`Score >= 75`** → 🟢 **AUTO APPROVE**
   - **`45 <= Score < 75`** → 🟡 **STEP_UP_REQUIRED** (Human-in-the-loop confirmation)
   - **`Score < 45` or Hard Rule** → 🔴 **HARD BLOCK**

---

## 🏛️ System Architecture & Execution Boundaries

```
User Prompt ("Buy groceries up to ₹10,000 this month")
           │
           ▼
LLM Intent Extraction (OpenAI / Gemini / Heuristic Fallback) ──► Structured IntentProfile
           │
           ▼
AI Agent Transaction Request (POST /transactions/evaluate)
           │
           ├────────► 1. Hard Rule Engine (Mandate ACTIVE, Remaining Limit, Category, 5s Duplicate)
           │             └── IF VIOLATED ──► 🔴 HARD BLOCK (Score 0, STOP)
           │
           ├────────► 2. Intent-Fit Scoring Engine (0-100 across 7 Signals)
           │             ├── Category Match (20)
           │             ├── Amount Deviation (25)
           │             ├── Frequency Deviation (15)
           │             ├── Merchant Familiarity (15)
           │             ├── Time Pattern Fit (5)
           │             ├── Velocity Proximity (10)
           │             └── Intent Similarity (10)
           │
           ▼
Policy Decision Engine
   ├── Score >= 75  ──► 🟢 AUTO APPROVE ──► SimulationProvider.execute() ──► COMPLETED
   ├── 45-74        ──► 🟡 STEP_UP_REQUIRED ──► User UI ──► APPROVE ──► COMPLETED
   │                                                    └── REJECT  ──► CANCELLED
   └── Score < 45   ──► 🔴 HARD BLOCK ──► No Money Movement
```

### AI vs Deterministic Boundary
- **AI Agent & LLM:** Interpret natural language intent and compute semantic similarity signals. AI **cannot** approve payments, override hard rules, modify mandates, or bypass policy.
- **Deterministic Engine:** Enforces final authority. Hard safety rules evaluate *before* scoring and force score = 0 on violation. `SimulationProvider.execute()` can **ONLY** be invoked when transaction state is `APPROVED` or `USER_APPROVED`.

---

## 🚀 Key Features

### ⚔️ Agent Red-Team / Attack Simulator
- Allows judges to intentionally attack the AI Agent pipeline to verify safety boundaries (`POST /red-team/run`).
- **6 Attack Scenarios:** Duplicate Payment Attack, Mandate Limit Attack, Category Switching Attack, Rapid-Fire Frequency Attack, Intent-Mismatch Attack, Malformed Request Attack.
- Dynamically computes attack metrics (Attacks Run, Blocked, Step-Up, Approved, Unsafe Actions).

### 🤖 Agent Behaviour Replay & Timeline
- Observes AI Agent transaction execution over time (`GET /agents/{id}/replay`).
- Computes deterministic **Behaviour Consistency** (`HIGH`, `MODERATE`, `LOW`) based on actual transaction outcomes and intent alignment without speculative ML models.

### 🔍 Decision Explainability Panel ("Why did DIV make this decision?")
- Displays structured decision evidence in the UI:
  1. **Delegated User Intent:** Natural language mandate text & budget limits.
  2. **Deterministic Safety Checks:** Pre-scoring check indicators.
  3. **Intent-Fit Score Signal Breakdown:** 7 weighted signal bars.
  4. **Final Policy Rationale:** Clear explanation distinguishing AI signals from deterministic policy decisions.

---

## 📊 Dynamic Evaluation Benchmark

| Evaluation Metric | DIV (Agentic Trust Layer) | Baseline 1 (Static Limit Only) | Baseline 2 (Simple Rules) |
|---|---|---|---|
| **Unsafe-Action Rate (Target: 0%)** | **0.0%** | **100.0%** | **50.0%** |
| **False Approval Rate** | **0.0%** | 100.0% | 50.0% |
| **Precision** | **100.0%** | 33.3% | 50.0% |
| **Recall** | **100.0%** | 100.0% | 100.0% |
| **F1 Score** | **100.0%** | 50.0% | 66.7% |
| **P50 Latency (Local Environment)** | **~55 ms** | ~1 ms | ~1 ms |

> ⚠️ **Synthetic Benchmark Disclaimer:** All benchmark metrics are dynamically calculated on replay (`POST /simulation/run`) using synthetic dataset test cases across 6 user archetypes. Latency figures represent local test environment execution. This system is designed as a trust layer for agentic payment workflows and does not claim production bank/rail integration or real-world zero-fraud guarantees.

---

## 🎬 5-Minute Recommended Demo Flow

1. **0:00 — Problem & Mandate Setup:** Explain agentic payment risk. Create a grocery mandate: *"Buy groceries for my family up to ₹3,000 weekly"*.
2. **1:00 — Auto-Approval Flow:** Trigger ₹850 grocery transaction → 🟢 `AUTO APPROVE` (Score 97.9/100).
3. **1:30 — Decision Explainability:** Inspect *"Why did DIV make this decision?"* showing pre-scoring safety checks & 7 weighted score bars.
4. **2:00 — Hard Duplicate Block:** Re-trigger same request within 5s → 🔴 `HARD BLOCK` (Score 0, `HARD_DUPLICATE_VIOLATION`).
5. **2:30 — Step-Up Confirmation:** Trigger ₹2,850 off-pattern bulk purchase → 🟡 `STEP_UP_REQUIRED` (Score 53/100). Click **Approve** → `USER_APPROVED` → `EXECUTING` → `COMPLETED`.
6. **3:00 — Agent Behaviour Replay:** Open `🤖 Agent Behaviour` tab to inspect agent timeline & `HIGH CONSISTENCY` badge.
7. **3:30 — Agent Red-Team Simulator:** Open `⚔️ Red-Team` tab and click **Run All Attacks**. Inspect 6 attack results and 0 unsafe actions card.
8. **4:20 — Immutable Audit Trail:** Open `🔍 Audit Trail` tab to inspect reconstructable state transitions.
9. **4:40 — Dynamic Benchmark Comparison:** Open `📊 Benchmark` tab to compare DIV (0% unsafe rate) against Static Limit (100% unsafe rate).

---

## 💻 Setup & Installation

### Backend Setup (Python 3.12, FastAPI)
```bash
cd backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt

# Run full backend test suite (33 passed)
$env:PYTHONPATH="."; pytest tests

# Start backend server
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Frontend Setup (React, Vite, TypeScript)
```bash
cd frontend
npm install
npm run build   # Production bundle verification
npm run dev     # Start Vite dev server on http://127.0.0.1:5173
```
Open [http://127.0.0.1:5173](http://127.0.0.1:5173) in your browser.
