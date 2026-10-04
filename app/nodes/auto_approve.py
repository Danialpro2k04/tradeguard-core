"""
Node 6a: Auto Approve (GREEN path)

When overall_risk is GREEN, the shipment is automatically cleared.
This node sets the pipeline status to "approved" and logs the clearance.
"""

from app.audit import create_audit_entry, get_previous_hash
from app.schemas import TradeComplianceState


def auto_approve(state: TradeComplianceState) -> dict:
    """Node 6a: Auto-clear the shipment (GREEN risk)."""
    prev_hash = get_previous_hash(state.get("audit_log", []))

    audit_entry = create_audit_entry(
        node_name="auto_approve",
        action="Shipment AUTO-CLEARED — all compliance checks passed",
        input_summary={"overall_risk": "GREEN"},
        output_summary={"pipeline_status": "approved", "method": "automatic"},
        previous_hash=prev_hash,
        risk_level="GREEN",
    )

    return {
        "pipeline_status": "approved",
        "human_decision": "approve",
        "human_justification": "Automatic clearance — all checks GREEN",
        "reviewed_by": "SYSTEM (auto-approve)",
        "audit_log": [audit_entry],
    }
