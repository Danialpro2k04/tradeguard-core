# TradeGuard Core Pipeline v0.1

> Autonomous trade compliance pipeline connecting document extraction, sanctions screening, and HS tariff classification into a single governed LangGraph agent with human-in-the-loop review.

## What This Does

A Bill of Lading goes in → a full compliance decision comes out.

```
📄 B/L Document
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  TradeGuard Core Pipeline (LangGraph State Machine)         │
│                                                             │
│  document_intake ──► entity_extraction ──► sanctions_screening│
│       ──► hs_classification ──► risk_assessment             │
│                    │                                        │
│         ┌─────────┼──────────┐                              │
│         ▼         ▼          ▼                              │
│      🟢 GREEN  🟡 YELLOW  🔴 RED                            │
│      Auto-     Human      Block &                           │
│      Approve   Review     Alert                             │
│         │      (pause)       │                              │
│         └────────┴───────────┘                              │
│                  │                                          │
│                  ▼                                          │
│          generate_report                                    │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
✅ Compliance Report + Hash-Chained Audit Trail
```

## Architecture

This pipeline connects **three Month 1 microservices** via HTTP calls:

| Service | Port | Purpose |
|---------|------|---------|
| `freight_document_scanner` | 8000 | Extract entities from B/L via Azure Document Intelligence |
| `sanctionscope` | 8001 | Screen entities against OFAC/EU/UN sanctions lists |
| `tariffai` | 8004 | Classify cargo into 6-digit HS tariff codes |
| **`tradeguard_core`** | **8005** | **Orchestrate all services via LangGraph** |

### Why LangGraph?

| Feature | Regular Function Chain | LangGraph Pipeline |
|---------|----------------------|-------------------|
| State persistence | ❌ Lost on crash | ✅ Checkpointed after every node |
| Pause for human review | ❌ Not possible | ✅ `interrupt()` pauses, resumes later |
| Conditional routing | ❌ Manual if/else | ✅ Declarative conditional edges |
| Audit trail | ❌ Manual logging | ✅ State reducers append automatically |
| Retry on failure | ❌ Restart everything | ✅ Resume from last checkpoint |

## Quick Start

### 1. Setup

```bash
cd ~/tradeguard/tradeguard_core
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Start Upstream Services

```bash
# Terminal 1: Qdrant (if not already running from tariffai)
cd ~/tradeguard/tariffai && docker compose up -d

# Terminal 2: SanctionScope (Week 3)
cd ~/tradeguard/sanctionscope
source venv/bin/activate
uvicorn app.main:app --port 8001

# Terminal 3: TariffAI (Week 4)
cd ~/tradeguard/tariffai
source venv/bin/activate
uvicorn app.main:app --port 8004

# Terminal 4: Document Scanner (Week 1-2) — optional, needs Azure
cd ~/tradeguard/freight_document_scanner
source venv/bin/activate
python3 app.py
```

### 3. Start the Core Pipeline

```bash
# Terminal 5:
cd ~/tradeguard/tradeguard_core
source venv/bin/activate
uvicorn app.main:app --reload --port 8005
```

### 4. Test It

**Option A: Direct input (no Azure needed)**
```bash
curl -s -X POST http://localhost:8005/process/direct \
  -H "Content-Type: application/json" \
  -d '{
    "shipper_name": "Pakistan Cotton Exports Ltd",
    "consignee_name": "Rotterdam Textiles BV",
    "cargo_description": "1X40HC STC 12000 PCS MENS 100% COTTON PIQUE POLO SHIRTS KNITTED",
    "port_of_loading": "Karachi",
    "port_of_discharge": "Rotterdam"
  }' | python3 -m json.tool
```

**Option B: Simulation mode (full pipeline, mock extraction)**
```bash
curl -s -X POST http://localhost:8005/process \
  -H "Content-Type: application/json" \
  -d '{
    "document_path": "/path/to/sample_bol.pdf",
    "simulation_mode": true
  }' | python3 -m json.tool
```

### 5. Check Report

Use the `document_id` from the response:

```bash
curl -s http://localhost:8005/report/TG-2026-10-XXXX | python3 -m json.tool
```

### 6. Human Review (for YELLOW-flagged shipments)

```bash
curl -s -X POST http://localhost:8005/review/TG-2026-10-XXXX \
  -H "Content-Type: application/json" \
  -d '{
    "decision": "approve",
    "justification": "Reviewed shipper history — legitimate textile exporter since 2018",
    "reviewed_by": "Danyal Wahdat"
  }' | python3 -m json.tool
```

## API Reference

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/process` | Submit a document for full pipeline processing |
| `POST` | `/process/direct` | Process pre-extracted data (skip document extraction) |
| `GET` | `/status/{document_id}` | Check pipeline status |
| `POST` | `/review/{document_id}` | Submit human review decision |
| `GET` | `/report/{document_id}` | Get full compliance report |
| `GET` | `/health` | Check connectivity to all services |
| `GET` | `/docs` | Interactive Swagger UI |

## Pipeline Nodes

| # | Node | External Call | Purpose |
|---|------|--------------|---------|
| 1 | `document_intake` | `freight_document_scanner` | Extract entities from B/L |
| 2 | `entity_extraction` | None (pure parsing) | Parse shipper, consignee, cargo |
| 3 | `sanctions_screening` | `sanctionscope` (×2) | Screen shipper + consignee |
| 4 | `hs_classification` | `tariffai` | Classify cargo → HS code |
| 5 | `risk_assessment` | None (aggregation) | Combine all signals → risk verdict |
| 6a | `auto_approve` | None | GREEN → clear shipment |
| 6b | `human_review` | None (`interrupt()`) | YELLOW → pause for human |
| 6c | `block_alert` | None | RED → block shipment |
| 7 | `generate_report` | None | Compile final compliance report |

## Risk Decision Matrix

```
IF sanctions_risk == RED:
    → overall_risk = RED → block_alert

ELIF sanctions_risk == YELLOW
  OR hs_confidence < 0.70
  OR document_discrepancies exist:
    → overall_risk = YELLOW → human_review (pause)

ELSE:
    → overall_risk = GREEN → auto_approve
```

## Audit Trail

Every node appends a hash-chained audit entry:

```json
{
  "timestamp": "2026-10-03T16:30:00Z",
  "node": "sanctions_screening",
  "action": "Screened shipper + consignee against OFAC/EU/UN sanctions lists",
  "input": {"shipper": "Pakistan Cotton Exports", "consignee": "Rotterdam Textiles"},
  "output": {"shipper_risk": "GREEN", "consignee_risk": "GREEN", "combined_risk": "GREEN"},
  "risk_level": "GREEN",
  "hash": "a3f2b1c4d5e6..."
}
```

Each entry's `hash = SHA256(previous_entry.hash + this_entry_json)`. If anyone modifies a past entry, every subsequent hash breaks → **tamper-evident**.

## Running Tests

```bash
cd ~/tradeguard/tradeguard_core
source venv/bin/activate
python3 -m pytest tests/ -v
# or run directly:
python3 -m tests.test_pipeline
```

## Tech Stack

- **LangGraph** — State machine orchestration, checkpointing, human-in-the-loop
- **FastAPI** — HTTP endpoints
- **Qdrant** — Vector search (shared by sanctionscope + tariffai)
- **Azure Document Intelligence** — B/L extraction
- **Google Gemini** — HS code classification reasoning
- **SHA-256 hash chains** — Tamper-evident audit trail

## License

MIT License — Copyright (c) 2026 Danyal Wahdat
