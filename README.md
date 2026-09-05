# VSPL Smart Manufacturing Execution System (SMES) + OMS

**AI Powered Production Tracking, Planning & Manufacturing Intelligence**  
*Vijay Spheroidals Pvt Ltd (VSPL)*

---

## 🏭 Overview

The **VSPL Smart Manufacturing Execution System (SMES)** integrates physical shop floor execution with the authoritative **VSPL OMS Engine**, a pure deterministic **Mathematical KPI Engine**, and a modular **Machine Learning & Statistical Intelligence Architecture**.

```text
OAR CREATION
     ↓
WORK ORDER CREATION
     ↓
WORK ORDER RELEASE (OMS Target & Match Size)
     ↓
DYNAMIC ROUTE EXECUTION (F1 ➔ F2 ➔ F3 ➔ SP ➔ FI)
     ↓
STAGE-WISE OK COMPLETED & REJECTION TRACKING
     ↓
PACKING / BSR VERIFICATION
     ↓
DISPATCH GATEKEEPER & INVOICING
     ↓
CONSERVATION OF MASS RECONCILIATION
```

---

## 🚀 Key Features

1. **Authoritative OMS Business Logic**:
   - Deterministic route validation and movement control.
   - Stage-isolated scrap and rejection traceability.
   - Strict dispatch eligibility gatekeeping preventing over-dispatch.
   - Conservation of mass reconciliation ($Released = TotalWIP + Dispatched + TotalScrap$).

2. **Mathematical KPI Engine** (`backend/app/analytics/math_engine.py`):
   - Zero-safe pure deterministic calculations for Achievement %, Yield %, Rejection Rate %, Production Velocity, Takt Time, Cycle Times, and OEE Proxy.

3. **Machine Learning & Statistical Intelligence** (`backend/app/analytics/ml_models.py`):
   - **Delivery Delay Risk Predictor** (Alloy machinability, route depth, batch size, buffer dwell time).
   - **Quality & Rejection Risk Model** (Bayesian defect rate prediction per machine cell).
   - **WIP Bottleneck Detector** (Buffer share congestion analysis).
   - **Statistical Production & WIP Forecaster** (Exponential smoothing & linear trend).
   - **Statistical Anomaly Detector** (Z-Score & IQR scrap spike scans).
   - **Model Governance & Feedback Loop** with explicit `INSUFFICIENT_DATA` guards.

4. **Modern Shop Floor Operator UI**:
   - Next.js 15, Tailwind CSS, TypeScript, tablet & mobile responsive.
   - Large stage-wise quantity displays (Target, OK Completed, Rejection, Live Status).
   - Barcode / QR scanner integration for shop floor travellers.

---

## 🛠️ Technology Stack

- **Backend**: FastAPI (Python 3.10+ / 3.14), SQLAlchemy ORM, PostgreSQL / SQLite, Pydantic v2.
- **Frontend**: Next.js 15 (App Router), React 18, Tailwind CSS, Lucide Icons, Axios.
- **Analytics & ML**: NumPy, Scikit-Learn, Pure Mathematical Functions.

---

## 🚦 Getting Started

### 1. Backend Setup
```bash
cd backend
python -m venv venv
# Windows:
.\venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 2. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) in your browser.

---

## 🧪 Testing & Verification

Run the full automated test suite:
```bash
cd backend
python -m pytest tests/
```
*Current test status: 24 / 24 tests passed (100%).*
