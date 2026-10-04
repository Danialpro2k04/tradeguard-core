"""
Node 6c: Block & Alert (RED path)

When overall_risk is RED (confirmed sanctions match), the shipment
is immediately blocked. In a production system, this would also
trigger alerts to the compliance team via email/Slack/webhook.
"""

from app.audit import create_audit_entry, get_previous_hash
from app.schemas import TradeComplianceState


def block_alert(state: TradeComplianceState) -> dict:
    """Node 6c: Block the shipment and generate an alert (RED risk)."""
    prev_hash = get_previous_hash(state.get("audit_log", []))

    audit_entry = create_audit_entry(
        node_name="block_alert",
        action="Shipment BLOCKED — sanctions match or human rejection",
        input_summary={
            "overall_risk": state.get("overall_risk"),
            "risk_factors": state.get("risk_factors", []),
        },
        output_summary={
            "pipeline_status": "blocked",
            "alert_sent": True,
        },
        previous_hash=prev_hash,
        risk_level="RED",
        metadata={
            "shipper": state.get("shipper_name", ""),
            "consignee": state.get("consignee_name", ""),
            "sanctions_risk": state.get("sanctions_risk", ""),
        },
    )

    return {
        "pipeline_status": "blocked",
        "audit_log": [audit_entry],
    }
