"""
Node 7: Report Generator

Compiles the full compliance report from all state fields.
This is the final node in every path (GREEN, YELLOW, RED).
It sets the completed_at timestamp and builds a structured
report object that can be returned via the API.
"""

from datetime import datetime, timezone

from app.audit import create_audit_entry, get_previous_hash, verify_audit_chain
from app.schemas import TradeComplianceState


def generate_report(state: TradeComplianceState) -> dict:
    """
    Node 7: Compile the final compliance report from all state fields.
    """
    prev_hash = get_previous_hash(state.get("audit_log", []))
    completed_at = datetime.now(timezone.utc).isoformat()

    # Calculate processing time
    started_at = state.get("started_at", "")
    processing_time_ms = 0.0
    if started_at:
        try:
            start = datetime.fromisoformat(started_at)
            end = datetime.fromisoformat(completed_at)
            processing_time_ms = (end - start).total_seconds() * 1000
        except (ValueError, TypeError):
            pass

    # Build human review summary
    human_review = None
    if state.get("human_decision") and state.get("reviewed_by", "").startswith("SYSTEM") is False:
        human_review = {
            "decision": state.get("human_decision"),
            "justification": state.get("human_justification", ""),
            "reviewed_by": state.get("reviewed_by", ""),
        }

    # Build sanctions summary
    shipper_screening = state.get("shipper_screening", {})
    consignee_screening = state.get("consignee_screening", {})

    shipper_summary = {
        "entity": state.get("shipper_name", ""),
        "risk_level": shipper_screening.get("risk_level", "N/A"),
        "matches_found": len(shipper_screening.get("matches", [])),
        "audit_id": shipper_screening.get("audit_id", ""),
    }
    consignee_summary = {
        "entity": state.get("consignee_name", ""),
        "risk_level": consignee_screening.get("risk_level", "N/A"),
        "matches_found": len(consignee_screening.get("matches", [])),
        "audit_id": consignee_screening.get("audit_id", ""),
    }

    # Build HS classification summary
    hs_result = state.get("hs_classification", {})
    hs_detail = hs_result.get("result", {}) if isinstance(hs_result, dict) else {}

    # Compile the report
    report = {
        "document_id": state.get("document_id", ""),
        "pipeline_status": state.get("pipeline_status", "unknown"),
        "overall_risk": state.get("overall_risk", ""),

        "extraction": {
            "shipper": state.get("shipper_name", ""),
            "consignee": state.get("consignee_name", ""),
            "cargo_description": state.get("cargo_description", ""),
            "port_of_loading": state.get("port_of_loading", ""),
            "port_of_discharge": state.get("port_of_discharge", ""),
            "discrepancies": state.get("document_discrepancies", []),
        },

        "sanctions_screening": {
            "combined_risk": state.get("sanctions_risk", ""),
            "shipper": shipper_summary,
            "consignee": consignee_summary,
        },

        "tariff_classification": {
            "hs_code": state.get("hs_code", ""),
            "description": hs_detail.get("primary_description", ""),
            "confidence": state.get("hs_confidence", 0.0),
            "is_ambiguous": hs_detail.get("is_ambiguous", False),
            "reasoning": hs_detail.get("reasoning", {}),
        },

        "risk_factors": state.get("risk_factors", []),
        "human_review": human_review,

        "timing": {
            "started_at": started_at,
            "completed_at": completed_at,
            "processing_time_ms": round(processing_time_ms, 2),
        },

        "audit_chain_length": len(state.get("audit_log", [])) + 1,  # +1 for this entry
    }

    # Verify audit chain integrity
    chain_valid, chain_msg = verify_audit_chain(state.get("audit_log", []))

    audit_entry = create_audit_entry(
        node_name="report_generator",
        action=f"Compiled final compliance report — status: {state.get('pipeline_status', '')}",
        input_summary={"state_fields_used": 12},
        output_summary={
            "pipeline_status": state.get("pipeline_status", ""),
            "overall_risk": state.get("overall_risk", ""),
            "processing_time_ms": round(processing_time_ms, 2),
            "audit_chain_valid": chain_valid,
        },
        previous_hash=prev_hash,
        metadata={"audit_chain_verification": chain_msg},
    )

    return {
        "compliance_report": report,
        "completed_at": completed_at,
        "audit_log": [audit_entry],
    }
