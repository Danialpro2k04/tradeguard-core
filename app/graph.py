"""
TradeGuard Core Pipeline — LangGraph State Machine

This is the orchestration brain. It defines:
  1. Which nodes exist
  2. The order they execute in (edges)
  3. When to branch (conditional edges based on risk level)
  4. When to pause for human review (checkpointing)

Graph topology:
  START → document_intake → entity_extraction → sanctions_screening
        → hs_classification → risk_assessment
        → [conditional routing]:
            GREEN  → auto_approve   → generate_report → END
            YELLOW → human_review   → [approve → generate_report → END]
                                    → [reject  → block_alert → generate_report → END]
            RED    → block_alert    → generate_report → END
"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from app.schemas import TradeComplianceState
from app.nodes.document_intake import document_intake
from app.nodes.entity_extraction import entity_extraction
from app.nodes.sanctions_screening import sanctions_screening
from app.nodes.hs_classification import hs_classification
from app.nodes.risk_assessment import risk_assessment
from app.nodes.auto_approve import auto_approve
from app.nodes.human_review import human_review
from app.nodes.block_alert import block_alert
from app.nodes.report_generator import generate_report


def route_by_risk(state: TradeComplianceState) -> str:
    """
    Conditional edge: route the pipeline based on overall_risk.

    This function is called AFTER risk_assessment runs.
    It reads overall_risk from the state and returns the name
    of the next node to execute.

    Returns:
        "auto_approve"  — for GREEN risk
        "human_review"  — for YELLOW risk (will pause)
        "block_alert"   — for RED risk
    """
    risk = state.get("overall_risk", "YELLOW")
    if risk == "GREEN":
        return "auto_approve"
    elif risk == "RED":
        return "block_alert"
    else:
        return "human_review"


def route_after_human_review(state: TradeComplianceState) -> str:
    """
    After a human makes a decision on a YELLOW-flagged shipment,
    route to either generate_report (approved) or block_alert (rejected).
    """
    decision = state.get("human_decision", "reject")
    if decision == "approve":
        return "generate_report"
    else:
        return "block_alert"


def build_graph():
    """
    Construct the LangGraph StateGraph with all nodes and edges.

    Returns:
        A compiled graph with MemorySaver checkpointing enabled.
        The checkpointer allows the graph to pause at human_review
        and resume later when the human submits a decision.
    """

    # ── 1. Create the graph with our typed state ──
    graph = StateGraph(TradeComplianceState)

    # ── 2. Add all processing nodes ──
    # Each node is a function: (state) -> partial state update
    graph.add_node("document_intake", document_intake)
    graph.add_node("entity_extraction", entity_extraction)
    graph.add_node("sanctions_screening", sanctions_screening)
    graph.add_node("hs_classification", hs_classification)
    graph.add_node("risk_assessment", risk_assessment)
    graph.add_node("auto_approve", auto_approve)
    graph.add_node("human_review", human_review)
    graph.add_node("block_alert", block_alert)
    graph.add_node("generate_report", generate_report)

    # ── 3. Define the sequential edges ──
    # START → document_intake → entity_extraction → ...
    graph.add_edge(START, "document_intake")
    graph.add_edge("document_intake", "entity_extraction")
    graph.add_edge("entity_extraction", "sanctions_screening")
    graph.add_edge("sanctions_screening", "hs_classification")
    graph.add_edge("hs_classification", "risk_assessment")

    # ── 4. Conditional routing after risk assessment ──
    # This is where the pipeline branches based on the risk verdict
    graph.add_conditional_edges(
        "risk_assessment",          # Source node
        route_by_risk,              # Routing function
        {                           # Map: return value → target node
            "auto_approve": "auto_approve",
            "human_review": "human_review",
            "block_alert": "block_alert",
        },
    )

    # ── 5. After GREEN auto-approve, generate report ──
    graph.add_edge("auto_approve", "generate_report")

    # ── 6. After YELLOW human review, route by decision ──
    graph.add_conditional_edges(
        "human_review",
        route_after_human_review,
        {
            "generate_report": "generate_report",
            "block_alert": "block_alert",
        },
    )

    # ── 7. After RED block, generate report ──
    graph.add_edge("block_alert", "generate_report")

    # ── 8. Report is the final node ──
    graph.add_edge("generate_report", END)

    # ── 9. Compile with checkpointing ──
    # MemorySaver stores state in memory (for dev/testing).
    # In production, you'd use SqliteSaver or PostgresSaver
    # for persistent cross-restart checkpoints.
    checkpointer = MemorySaver()
    compiled = graph.compile(checkpointer=checkpointer)

    return compiled


# Module-level graph instance (created once, reused by FastAPI)
pipeline = build_graph()
