"""
Node 5: Risk Assessment

Pure aggregation logic — no external service calls. Combines signals
from all previous nodes into a single overall risk verdict.

Decision Matrix:
  RED    → sanctions_risk == RED
  YELLOW → sanctions_risk == YELLOW
           OR hs_confidence < 0.70
           OR document_discrepancies exist
           OR critical fields missing
  GREEN  → everything clean
"""

from app.config import HS_CONFIDENCE_THRESHOLD
from app.audit import create_audit_entry, get_previous_hash
from app.schemas import TradeComplianceState


def risk_assessment(state: TradeComplianceState) -> dict:
    """
    Node 5: Aggregate all signals into an overall risk verdict.
    """
    prev_hash = get_previous_hash(state.get("audit_log", []))

    sanctions_risk = state.get("sanctions_risk", "GREEN")
    hs_confidence = state.get("hs_confidence", 0.0)
    discrepancies = state.get("document_discrepancies", [])
    existing_risk_factors = state.get("risk_factors", [])

    # ── Decision logic ──
    new_risk_factors = []

    if sanctions_risk == "RED":
        overall_risk = "RED"

    elif sanctions_risk == "YELLOW":
        overall_risk = "YELLOW"

    elif hs_confidence < HS_CONFIDENCE_THRESHOLD and state.get("hs_code"):
        overall_risk = "YELLOW"
        new_risk_factors.append(
            f"HS confidence ({hs_confidence:.0%}) below threshold ({HS_CONFIDENCE_THRESHOLD:.0%})"
        )

    elif discrepancies:
        overall_risk = "YELLOW"

    elif not state.get("shipper_name") or not state.get("consignee_name"):
        overall_risk = "YELLOW"

    else:
        overall_risk = "GREEN"

    human_review_required = overall_risk in ("YELLOW", "RED")

    audit_entry = create_audit_entry(
        node_name="risk_assessment",
        action=f"Aggregated compliance signals → overall risk: {overall_risk}",
        input_summary={
            "sanctions_risk": sanctions_risk,
            "hs_code": state.get("hs_code", ""),
            "hs_confidence": hs_confidence,
            "discrepancies": len(discrepancies),
            "prior_risk_factors": len(existing_risk_factors),
        },
        output_summary={
            "overall_risk": overall_risk,
            "human_review_required": human_review_required,
            "total_risk_factors": len(existing_risk_factors) + len(new_risk_factors),
        },
        previous_hash=prev_hash,
        risk_level=overall_risk,
    )

    status = "awaiting_review" if overall_risk == "YELLOW" else "processing"

    return {
        "overall_risk": overall_risk,
        "pipeline_status": status,
        "human_review_required": human_review_required,
        "risk_factors": new_risk_factors,
        "audit_log": [audit_entry],
    }
