# Delegated Intent Verifier (DIV)

Prototype agentic payment trust layer for delegated AI-initiated payment workflows.

**Track:** Razorpay AI Buildathon 2026 — Track 2: AI Risk Manager  
**Positioning:** Agentic Payment Trust Layer for AI-Initiated Payments (Designed for UPI Reserve Pay workflows)  
**Status:** Feature-Complete & Verified (33 Passing Tests, Dynamic Synthetic Evaluation Engine)  

---

## 🎬 Live Demo

**[Watch the 5-Minute DIV Demo](https://drive.google.com/file/d/18nbMSJQy84A37jvURqaDKrTitpXRXgGv/view?usp=sharing)**

> This demo shows the real DIV application running locally, including natural-language mandate creation, intent-fit decisions, deterministic safety checks, step-up confirmation, payment execution boundaries, Red-Team attacks, Agent Behaviour Replay, Audit Trail inspection, and dynamic benchmark evaluation.

---

## 💡 The Problem

Autonomous AI Agents are increasingly empowered to initiate financial transactions on behalf of users (e.g., grocery shopping, travel booking, utility payments). However, traditional financial controls only answer:

> *"Can the agent spend this much?"*

Static spending limits fail when autonomous agents encounter real-world operational and alignment risks:
- **Retry loops** causing unintended duplicate payments
- **Category switching** (e.g. purchasing electronics under a grocery mandate)
- **Spending-limit abuse** and rapid-fire transaction patterns
- **Unusual purchase behavior** deviating from temporal or frequency patterns
- **Intent mismatch** between natural-language user instructions and transaction parameters
- **Autonomous agents acting without human confirmation** on ambiguous or high-risk requests

---

## 🛡️ The Solution

The **Delegated Intent Verifier (DIV)** introduces an agentic payment trust layer positioned between AI Agents and payment execution rails.

**DIV** answers:

> *"Is the agent spending in a way the user actually intended?"*

It evaluates every AI-initiated payment against four core pillars:
1. **Natural Language Mandates:** Converted by LLM into a structured `IntentProfile` (e.g., *"You can buy groceries for my family up to ₹10,000 this month"* with a total budget of ₹10,000 and a per-transaction cap of ₹3,000).
2. **Deterministic Hard Safety Rules:** Evaluated *before* scoring to immediately block invalid or duplicate requests.
3. **Intent-Fit Scoring Engine:** Evaluates 7 weighted behavioral and intent alignment signals (0–100 total score).
4. **Policy Decision Engine:**
   - **`Score >= 75`** → 🟢 **AUTO APPROVE**
   - **`45 <= Score < 75`** → 🟡 **STEP_UP_REQUIRED** (Human-in-the-loop user confirmation)
   - **`Score < 45` or Hard Rule Violation** → 🔴 **HARD BLOCK**

---

## 🏛️ System Architecture & Execution Boundaries

```
Natural Language Mandate ("You can buy groceries for my family up to ₹10,000 this month")
           │
           ▼
LLM Intent Extraction (OpenAI / Gemini / Heuristic Fallback) ──► Structured IntentProfile
           │
           ▼
Transaction Request (POST /transactions/evaluate)
           │
           ├────────► 1. Deterministic Hard Safety Checks
           │             (Mandate ACTIVE, Remaining Limit, Category Authorization, 5s Duplicate Check)
           │             └── IF VIOLATED ──► 🔴 HARD BLOCK (Score 0, Immediate Rejection)
           │
           ├────────► 2. Intent-Fit Scoring Engine (7 Weighted Signals, Total = 100)
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
   ├── 45-74        ──► 🟡 STEP_UP_REQUIRED ──► User UI Confirmation ──► APPROVE ──► COMPLETED
   │                                                             └── REJECT  ──► CANCELLED
   └── Score < 45   ──► 🔴 HARD BLOCK ──► No Payment Execution
```

### AI vs Deterministic Boundary

- **AI/LLM Layer:** Interprets natural-language user intent, extracts structured `IntentProfile`, and contributes bounded semantic intent signals. The LLM **cannot** approve payments, override hard safety rules, alter mandates, or directly trigger transaction execution.
- **Deterministic Engine:** Retains final authority. Hard safety rules evaluate *before* scoring, enforcing strict limits, authorized categories, duplicate detection, and mandate state. `SimulationProvider.execute()` can **ONLY** be invoked after a transaction reaches `APPROVED` or `USER_APPROVED` state, guaranteeing strict payment execution boundaries.

---

## 🚀 Key Features

### ⚔️ Agent Red-Team / Attack Simulator

Interactively test and attack the AI Agent safety pipeline through `POST /red-team/run` to verify safety enforcement under malicious or buggy agent behaviors.

- **6 Evaluated Attack Scenarios:**
  - **Duplicate Payment:** Rapid retry loop attempting double charge.
  - **Mandate Limit:** Transaction exceeding remaining or per-transaction mandate cap.
  - **Category Switching:** Unauthorized merchant category purchase.
  - **Rapid-Fire Frequency:** Burst transactions violating frequency bounds.
  - **Intent Mismatch:** Transaction context conflicting with original intent.
  - **Malformed Request:** Structural or parameter payload manipulation.
- Attacks are dynamically evaluated through the live DIV safety pipeline, providing real-time safety metrics (Attacks Run, Hard Blocked, Step-Up Required, Approved, Unsafe Action Rate).

### 🤖 Agent Behaviour Replay & Timeline

Inspect chronological agent transaction history and behavior patterns over time via `GET /agents/{id}/replay`.

- Displays full transaction history, policy decision distribution, hard safety violations, and intent alignment over time.
- Computes deterministic **Behaviour Consistency** (`HIGH`, `MODERATE`, `LOW`) directly from verified historical outcomes without speculative ML models.

### 🔍 Decision Explainability

The UI Decision Inspector provides complete visibility into why DIV made each decision:
- **Delegated Intent & Mandate State:** Active mandate parameters, total budget remaining (₹10,000), and per-transaction cap (₹3,000).
- **Deterministic Safety Checks:** Pre-scoring verification status (Active status, category authorization, budget check, velocity check).
- **7 Scoring Components:** Clear visual breakdown of score contributions across Category (20), Amount (25), Frequency (15), Merchant Familiarity (15), Time Pattern (5), Velocity Proximity (10), and Intent Similarity (10).
- **Policy Decision & Rationale:** Explicit decision status and policy explanation distinguishing AI semantic signals from hard safety rules.

---

## 📊 Dynamic Evaluation Benchmark

The dynamic benchmark suite measures DIV performance against baseline payment control mechanisms using synthetic transaction datasets across 6 user/agent archetypes (`POST /simulation/run`).

| Evaluation Metric | DIV (Agentic Trust Layer) | Baseline 1 (Static Limit Only) | Baseline 2 (Simple Rules) |
|---|---|---|---|
| **Unsafe-Action Rate (Target: 0%)** | **0.0%** | **100.0%** | **50.0%** |
| **False Approval Rate** | **0.0%** | 100.0% | 50.0% |
| **Precision** | **100.0%** | 33.3% | 50.0% |
| **Recall** | **100.0%** | 100.0% | 100.0% |
| **F1 Score** | **100.0%** | 50.0% | 66.7% |
| **P50 Latency (Local Environment)** | **~55 ms** | ~1 ms | ~1 ms |

> ⚠️ **Synthetic Benchmark Disclaimer:** All evaluation metrics are dynamically calculated via synthetic dataset replay across six user and agent archetypes. Latency figures are measured in a local development environment. This project is a prototype trust layer for delegated AI payment workflows and does NOT claim production payment-rail integration or zero real-world fraud guarantees.

---

## 🎬 5-Minute Recommended Demo Flow

1. **Problem & Natural Language Mandate:** Set up mandate: *"You can buy groceries for my family up to ₹10,000 this month"* (Total budget: ₹10,000, Per-transaction cap: ₹3,000).
2. **₹850 Grocery Purchase:** Trigger valid transaction → 🟢 `AUTO APPROVE` (Score >= 75).
3. **Decision Explainability:** Inspect pre-scoring safety checks, 7 scoring signal components, and decision rationale.
4. **₹2,850 Off-Pattern Purchase:** Trigger off-pattern stock-up transaction → 🟡 `STEP_UP_REQUIRED` (Score between 45 and 74).
5. **Step-Up Confirmation:** User confirms in UI → `USER_APPROVED` → `EXECUTING` → `COMPLETED`.
6. **Red-Team Attack Simulator:** Run automated attack suite (Duplicate Payment, Mandate Limit, Category Switching, Rapid-Fire Frequency, Intent Mismatch, Malformed Request) → 0 Unsafe Actions.
7. **Agent Behaviour Replay:** Review chronological timeline, decision distribution, and behaviour consistency rating.
8. **Audit Trail:** Reconstruct state transitions and execution logs in the Audit Trail tab.
9. **Dynamic Benchmark:** Compare DIV (0.0% unsafe rate) against Static Limit and Simple Rules baselines.

---

## 🧰 Tech Stack

- **Backend:** Python, FastAPI, SQLAlchemy, Pydantic
- **Frontend:** React, TypeScript, Vite
- **Database:** SQLite for prototype/local evaluation
- **AI Intent Extraction:** OpenAI / Gemini / Heuristic Fallback
- **Testing:** Pytest
- **Evaluation:** Synthetic Dataset + Dynamic Benchmark Replay

---

## 💻 Setup & Installation

### Backend Setup

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

### Frontend Setup

```bash
cd frontend
npm install
npm run build   # Production bundle verification
npm run dev     # Start Vite dev server on http://127.0.0.1:5173
```

After starting the frontend, open the local development server shown by Vite (typically `http://127.0.0.1:5173`).

---

## ✅ Project Status

- 33 automated tests passing
- Frontend production build verified
- Deterministic hard safety rules verified
- Payment execution boundary verified
- Idempotency and double-execution protection verified
- Red-Team attack simulator verified
- Agent Behaviour Replay verified
- Decision Explainability verified
- Dynamic synthetic benchmark verified
