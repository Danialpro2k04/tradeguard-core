"""
TradeGuard Core Pipeline — FastAPI Application

Endpoints:
  POST  /process           — Submit a document for full compliance processing
  POST  /process/direct    — Submit pre-extracted data (skip document extraction)
  GET   /status/{doc_id}   — Check pipeline status
  POST  /review/{doc_id}   — Submit human review decision (resume paused pipeline)
  GET   /report/{doc_id}   — Get the full compliance report
  GET   /health            — Health check (connectivity to all 3 services)
"""

import uuid
from datetime import datetime, timezone

import requests
from fastapi import FastAPI, HTTPException
from langgraph.types import Command

from app.config import (
    DOCUMENT_SCANNER_URL,
    SANCTIONSCOPE_URL,
    TARIFFAI_URL,
    SIMULATION_MODE,
    SERVICE_TIMEOUT,
)
from app.graph import pipeline
from app.schemas import (
    ProcessRequest,
    ProcessDirectRequest,
    ReviewRequest,
    PipelineStatusResponse,
    ComplianceReportResponse,
)


app = FastAPI(
    title="TradeGuard Core Pipeline",
    description=(
        "Autonomous trade compliance pipeline connecting document extraction, "
        "sanctions screening, and HS tariff classification into a single "
        "governed agent with human-in-the-loop review."
    ),
    version="0.1.0",
)


# ═══════════════════════════════════════════════════════════════
# In-memory state store (maps document_id → thread_id for LangGraph)
# In production, this would be a database
# ═══════════════════════════════════════════════════════════════
document_threads: dict[str, str] = {}


def _generate_document_id() -> str:
    """Generate a human-readable document ID like TG-2026-10-001."""
    now = datetime.now(timezone.utc)
    short_uuid = uuid.uuid4().hex[:4].upper()
    return f"TG-{now.strftime('%Y-%m')}-{short_uuid}"


def _get_latest_state(thread_id: str) -> dict:
    """Retrieve the latest state snapshot from the LangGraph checkpointer."""
    config = {"configurable": {"thread_id": thread_id}}
    state = pipeline.get_state(config)
    return state.values if state and state.values else {}


# ═══════════════════════════════════════════════════════════════
# POST /process — Full pipeline (document → compliance verdict)
# ═══════════════════════════════════════════════════════════════

@app.post("/process", response_model=PipelineStatusResponse)
def process_document(req: ProcessRequest):
    """
    Submit a trade document for full compliance processing.

    The pipeline will:
    1. Extract entities from the document via freight_document_scanner
    2. Screen shipper + consignee against sanctions lists
    3. Classify cargo into an HS tariff code
    4. Assess overall risk and route accordingly

    If risk is YELLOW, the pipeline pauses and returns status "awaiting_review".
    Use POST /review/{document_id} to submit a human decision.
    """
    doc_id = _generate_document_id()
    thread_id = f"thread-{doc_id}"
    document_threads[doc_id] = thread_id

    initial_state = {
        "document_id": doc_id,
        "raw_document_path": req.document_path,
        "simulation_mode": req.simulation_mode or SIMULATION_MODE,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_status": "processing",
        "extraction_result": {},
        "shipper_name": "",
        "consignee_name": "",
        "cargo_description": "",
        "port_of_loading": "",
        "port_of_discharge": "",
        "document_discrepancies": [],
        "shipper_screening": {},
        "consignee_screening": {},
        "sanctions_risk": "",
        "hs_classification": {},
        "hs_code": "",
        "hs_confidence": 0.0,
        "overall_risk": "",
        "risk_factors": [],
        "human_review_required": False,
        "human_decision": "",
        "human_justification": "",
        "reviewed_by": "",
        "audit_log": [],
        "compliance_report": {},
        "completed_at": "",
    }

    config = {"configurable": {"thread_id": thread_id}}

    # Run the graph — it will stop at interrupt() if YELLOW
    pipeline.invoke(initial_state, config)

    # Get the state after execution (or pause)
    state = _get_latest_state(thread_id)

    return PipelineStatusResponse(
        document_id=doc_id,
        pipeline_status=state.get("pipeline_status", "processing"),
        overall_risk=state.get("overall_risk", ""),
        risk_factors=state.get("risk_factors", []),
        human_review_required=state.get("human_review_required", False),
        started_at=state.get("started_at", ""),
        completed_at=state.get("completed_at"),
    )


# ═══════════════════════════════════════════════════════════════
# POST /process/direct — Skip document extraction, feed data directly
# ═══════════════════════════════════════════════════════════════

@app.post("/process/direct", response_model=PipelineStatusResponse)
def process_direct(req: ProcessDirectRequest):
    """
    Process pre-extracted trade data directly (skips document extraction).

    Useful for:
    - Testing the pipeline without Azure Document Intelligence
    - Integrating with external extraction systems
    - Processing data from the WhatsApp interface
    """
    doc_id = _generate_document_id()
    thread_id = f"thread-{doc_id}"
    document_threads[doc_id] = thread_id

    # Pre-fill the state with the provided data,
    # skipping the document_intake and entity_extraction nodes
    initial_state = {
        "document_id": doc_id,
        "raw_document_path": "direct_input",
        "simulation_mode": False,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_status": "processing",
        "extraction_result": {"status": "direct_input", "method": "pre-extracted"},
        "shipper_name": req.shipper_name,
        "consignee_name": req.consignee_name,
        "cargo_description": req.cargo_description,
        "port_of_loading": req.port_of_loading,
        "port_of_discharge": req.port_of_discharge,
        "document_discrepancies": [],
        "shipper_screening": {},
        "consignee_screening": {},
        "sanctions_risk": "",
        "hs_classification": {},
        "hs_code": "",
        "hs_confidence": 0.0,
        "overall_risk": "",
        "risk_factors": [],
        "human_review_required": False,
        "human_decision": "",
        "human_justification": "",
        "reviewed_by": "",
        "audit_log": [],
        "compliance_report": {},
        "completed_at": "",
    }

    config = {"configurable": {"thread_id": thread_id}}
    pipeline.invoke(initial_state, config)
    state = _get_latest_state(thread_id)

    return PipelineStatusResponse(
        document_id=doc_id,
        pipeline_status=state.get("pipeline_status", "processing"),
        overall_risk=state.get("overall_risk", ""),
        risk_factors=state.get("risk_factors", []),
        human_review_required=state.get("human_review_required", False),
        started_at=state.get("started_at", ""),
        completed_at=state.get("completed_at"),
    )


# ═══════════════════════════════════════════════════════════════
# GET /status/{document_id} — Check pipeline status
# ═══════════════════════════════════════════════════════════════

@app.get("/status/{document_id}", response_model=PipelineStatusResponse)
def get_status(document_id: str):
    """Check the current status of a document in the pipeline."""
    thread_id = document_threads.get(document_id)
    if not thread_id:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found")

    state = _get_latest_state(thread_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"No state found for {document_id}")

    return PipelineStatusResponse(
        document_id=document_id,
        pipeline_status=state.get("pipeline_status", "unknown"),
        overall_risk=state.get("overall_risk", ""),
        risk_factors=state.get("risk_factors", []),
        human_review_required=state.get("human_review_required", False),
        started_at=state.get("started_at", ""),
        completed_at=state.get("completed_at"),
    )


# ═══════════════════════════════════════════════════════════════
# POST /review/{document_id} — Human review decision
# ═══════════════════════════════════════════════════════════════

@app.post("/review/{document_id}", response_model=PipelineStatusResponse)
def submit_review(document_id: str, req: ReviewRequest):
    """
    Submit a human compliance officer's review decision.

    This resumes a pipeline that was paused at the human_review node.
    The decision (approve/reject) and justification are injected into
    the pipeline state, and execution continues.
    """
    thread_id = document_threads.get(document_id)
    if not thread_id:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found")

    state = _get_latest_state(thread_id)
    if state.get("pipeline_status") != "awaiting_review":
        raise HTTPException(
            status_code=400,
            detail=f"Document {document_id} is not awaiting review "
                   f"(current status: {state.get('pipeline_status', 'unknown')})",
        )

    # Resume the paused graph with the human's decision
    config = {"configurable": {"thread_id": thread_id}}
    human_input = {
        "decision": req.decision,
        "justification": req.justification,
        "reviewed_by": req.reviewed_by,
    }

    # Command(resume=value) resumes the interrupt() call in human_review node
    # The value passed here becomes the return value of interrupt()
    pipeline.invoke(Command(resume=human_input), config)

    # Get updated state after resumption
    state = _get_latest_state(thread_id)

    return PipelineStatusResponse(
        document_id=document_id,
        pipeline_status=state.get("pipeline_status", "unknown"),
        overall_risk=state.get("overall_risk", ""),
        risk_factors=state.get("risk_factors", []),
        human_review_required=False,
        started_at=state.get("started_at", ""),
        completed_at=state.get("completed_at"),
    )


# ═══════════════════════════════════════════════════════════════
# GET /report/{document_id} — Full compliance report
# ═══════════════════════════════════════════════════════════════

@app.get("/report/{document_id}")
def get_report(document_id: str):
    """
    Get the full compliance report for a processed document.
    Includes extraction results, sanctions screening, HS classification,
    risk assessment, human review decision, and full audit trail.
    """
    thread_id = document_threads.get(document_id)
    if not thread_id:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found")

    state = _get_latest_state(thread_id)
    report = state.get("compliance_report")

    if not report:
        # Pipeline hasn't finished yet — build a partial report
        return {
            "document_id": document_id,
            "pipeline_status": state.get("pipeline_status", "processing"),
            "message": "Pipeline has not completed yet. Check /status for current state.",
            "partial_data": {
                "overall_risk": state.get("overall_risk", ""),
                "risk_factors": state.get("risk_factors", []),
                "sanctions_risk": state.get("sanctions_risk", ""),
                "hs_code": state.get("hs_code", ""),
            },
        }

    # Attach the full audit trail
    report["audit_trail"] = state.get("audit_log", [])
    return report


# ═══════════════════════════════════════════════════════════════
# GET /health — Check connectivity to all downstream services
# ═══════════════════════════════════════════════════════════════

@app.get("/health")
def health_check():
    """
    Health check that verifies connectivity to all Month 1 services.
    Returns the status of each service and the overall system health.
    """
    services = {
        "document_scanner": {
            "url": DOCUMENT_SCANNER_URL,
            "check_path": "/",
        },
        "sanctionscope": {
            "url": SANCTIONSCOPE_URL,
            "check_path": "/docs",
        },
        "tariffai": {
            "url": TARIFFAI_URL,
            "check_path": "/health",
        },
    }

    results = {}
    all_healthy = True

    for name, svc in services.items():
        try:
            resp = requests.get(
                f"{svc['url']}{svc['check_path']}",
                timeout=5,
            )
            results[name] = {
                "status": "healthy" if resp.status_code < 400 else "degraded",
                "url": svc["url"],
                "status_code": resp.status_code,
            }
        except requests.exceptions.ConnectionError:
            results[name] = {
                "status": "offline",
                "url": svc["url"],
                "error": "Connection refused",
            }
            all_healthy = False
        except Exception as e:
            results[name] = {
                "status": "error",
                "url": svc["url"],
                "error": str(e)[:100],
            }
            all_healthy = False

    return {
        "status": "healthy" if all_healthy else "degraded",
        "pipeline": "tradeguard_core v0.1.0",
        "services": results,
        "note": "Use POST /process/direct to test pipeline without document_scanner",
    }
