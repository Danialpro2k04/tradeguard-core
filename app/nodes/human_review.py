"""
Node 6b: Human Review (YELLOW path)

When overall_risk is YELLOW, the pipeline PAUSES execution and waits
for a human compliance officer to make a decision.

This uses LangGraph's interrupt() function, which:
  1. Serializes the entire pipeline state to the checkpoint store
  2. Returns a "pause" signal to the caller
  3. Resumes later when the human submits a decision via the API

The human's decision (approve/reject + justification) is injected
back into the state when the pipeline resumes.
"""

from langgraph.types import interrupt

from app.audit import create_audit_entry, get_previous_hash
from app.schemas import TradeComplianceState


def human_review(state: TradeComplianceState) -> dict:
    """
    Node 6b: Pause the pipeline for human review.

    Uses LangGraph interrupt() — this literally stops execution.
    The pipeline resumes when a human calls POST /review/{document_id}.
    """
    prev_hash = get_previous_hash(state.get("audit_log", []))

    # Log that we're pausing for human review
    pause_audit = create_audit_entry(
        node_name="human_review",
        action="Pipeline PAUSED — awaiting human compliance officer review",
        input_summary={
            "overall_risk": state.get("overall_risk"),
            "risk_factors": state.get("risk_factors", []),
        },
        output_summary={"pipeline_status": "awaiting_review"},
        previous_hash=prev_hash,
        risk_level=state.get("overall_risk", "YELLOW"),
    )

    # ══════════════════════════════════════════════════════════
    # THIS IS THE KEY LANGGRAPH FEATURE:
    # interrupt() pauses the pipeline and returns a value to the
    # caller. When the pipeline is resumed (via graph.invoke with
    # the same thread_id), the interrupt() call returns the value
    # that was passed in during resumption.
    # ══════════════════════════════════════════════════════════
    human_input = interrupt({
        "message": "Shipment flagged for compliance review",
        "document_id": state.get("document_id", ""),
        "overall_risk": state.get("overall_risk", "YELLOW"),
        "risk_factors": state.get("risk_factors", []),
        "action_required": "Call POST /review/{document_id} with approve/reject + justification",
    })

    # When we get here, the human has responded
    decision = human_input.get("decision", "reject")
    justification = human_input.get("justification", "No justification provided")
    reviewed_by = human_input.get("reviewed_by", "Unknown Officer")

    # Log the human's decision
    decision_audit = create_audit_entry(
        node_name="human_review",
        action=f"Human compliance officer DECISION: {decision.upper()}",
        input_summary={
            "officer": reviewed_by,
            "risk_factors_reviewed": state.get("risk_factors", []),
        },
        output_summary={
            "decision": decision,
            "justification": justification,
        },
        previous_hash=pause_audit["hash"],
    )

    new_status = "approved" if decision == "approve" else "blocked"

    return {
        "pipeline_status": new_status,
        "human_decision": decision,
        "human_justification": justification,
        "reviewed_by": reviewed_by,
        "audit_log": [pause_audit, decision_audit],
    }
