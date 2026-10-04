"""
Node 1: Document Intake

Receives a raw trade document (PDF/image) and sends it to the
freight_document_scanner service for extraction via Azure Document
Intelligence. In simulation mode, returns pre-built sample data.

This is the entry point of the pipeline. It produces:
  - extraction_result: the full JSON response from the scanner
"""

import requests
from datetime import datetime, timezone

from app.config import DOCUMENT_SCANNER_URL, SERVICE_TIMEOUT
from app.audit import create_audit_entry, get_previous_hash
from app.schemas import TradeComplianceState


# ── Sample data for simulation mode (no Azure needed) ────────
SIMULATION_EXTRACTION = {
    "status": "success",
    "total_files_uploaded": 1,
    "total_pages_analyzed": 1,
    "classifications": [
        {"page": 1, "doc_type": "bill_of_lading"}
    ],
    "requires_human_review": False,
    "discrepancies": [],
    "low_confidence_flags": [],
    "extracted_data": {
        "page_0_bill_of_lading": {
            "ShipperName": "Pakistan Cotton Exports Ltd",
            "ConsigneeName": "Rotterdam Textiles BV",
            "NotifyParty": "ABC Freight Forwarding",
            "PortOfLoading": "Karachi",
            "PortOfDischarge": "Rotterdam",
            "CargoDescription": "1X40HC STC 12000 PCS MENS 100% COTTON PIQUE POLO SHIRTS KNITTED SIZES S-XXL",
            "ContainerNumber": "MSCU7829104",
            "VesselName": "MSC ANNA",
            "BillOfLadingNumber": "MSCUKHI-2026-001",
            "GrossWeight": "8500 KGS",
        }
    },
}


def document_intake(state: TradeComplianceState) -> dict:
    """
    Node 1: Send the raw document to freight_document_scanner for extraction.

    In simulation mode, skips the HTTP call and returns pre-built sample data.
    This allows testing the full pipeline without Azure Document Intelligence.
    """
    prev_hash = get_previous_hash(state.get("audit_log", []))

    # ── Direct input mode: data already pre-filled, skip extraction ──
    if state.get("raw_document_path") == "direct_input":
        audit_entry = create_audit_entry(
            node_name="document_intake",
            action="Skipped document extraction — data provided directly via /process/direct",
            input_summary={"method": "direct_input"},
            output_summary={"status": "pre-filled"},
            previous_hash=prev_hash,
            metadata={"direct_input": True},
        )
        return {
            "extraction_result": {"status": "direct_input", "method": "pre-extracted"},
            "audit_log": [audit_entry],
        }

    if state.get("simulation_mode", False):
        # ── Simulation mode: return sample data ──
        audit_entry = create_audit_entry(
            node_name="document_intake",
            action="Received trade document (SIMULATION MODE — using sample B/L data)",
            input_summary={"document_path": state.get("raw_document_path", "simulation")},
            output_summary={"status": "success", "pages": 1, "doc_type": "bill_of_lading"},
            previous_hash=prev_hash,
            metadata={"simulation": True},
        )
        return {
            "extraction_result": SIMULATION_EXTRACTION,
            "audit_log": [audit_entry],
        }

    # ── Live mode: call freight_document_scanner ──
    try:
        doc_path = state["raw_document_path"]
        with open(doc_path, "rb") as f:
            files = [("files", (doc_path.split("/")[-1], f, "application/pdf"))]
            response = requests.post(
                f"{DOCUMENT_SCANNER_URL}/api/extract",
                files=files,
                timeout=SERVICE_TIMEOUT,
            )
        response.raise_for_status()
        result = response.json()

        audit_entry = create_audit_entry(
            node_name="document_intake",
            action="Extracted entities from trade document via Azure Document Intelligence",
            input_summary={"document_path": doc_path},
            output_summary={
                "status": result.get("status"),
                "pages": result.get("total_pages_analyzed"),
                "discrepancies_found": len(result.get("discrepancies", [])),
            },
            previous_hash=prev_hash,
        )
        return {
            "extraction_result": result,
            "audit_log": [audit_entry],
        }

    except Exception as e:
        audit_entry = create_audit_entry(
            node_name="document_intake",
            action=f"FAILED to extract document: {str(e)[:200]}",
            input_summary={"document_path": state.get("raw_document_path", "unknown")},
            output_summary={"error": str(e)[:200]},
            previous_hash=prev_hash,
            risk_level="YELLOW",
        )
        return {
            "extraction_result": {"status": "error", "error": str(e)[:200]},
            "risk_factors": [f"Document extraction failed: {str(e)[:100]}"],
            "audit_log": [audit_entry],
        }
