"""
TradeGuard Core Pipeline — State Schema & Data Models

This is the most important file in the project. The TradeComplianceState
is a typed dictionary that flows through EVERY node in the LangGraph
pipeline. Each node reads what it needs, writes what it produces.

Key LangGraph concept:
  Annotated[list, operator.add] is a REDUCER.
  When a node returns {"audit_log": [new_entry]}, LangGraph doesn't
  overwrite the list — it APPENDS to it. This is how multiple nodes
  contribute to the same growing list without losing previous entries.
"""

from __future__ import annotations

import operator
from datetime import datetime
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════════════════════
# LangGraph State (flows through every node)
# ═══════════════════════════════════════════════════════════════

class TradeComplianceState(TypedDict):
    """
    The single source of truth for the entire compliance pipeline.

    Every node reads from this state and returns a partial update.
    LangGraph merges the update into the state automatically.

    Fields marked with Annotated[list, operator.add] use the ADD
    reducer — nodes append to these lists rather than overwriting them.
    """

    # ── Document Intake ──────────────────────────────────────
    document_id: str                    # Unique ID: "TG-2026-10-001"
    raw_document_path: str              # Path to uploaded file
    simulation_mode: bool               # True = use mock data (no Azure)

    # ── Extraction Results ───────────────────────────────────
    extraction_result: dict             # Raw response from freight_document_scanner
    shipper_name: str                   # Extracted shipper company name
    consignee_name: str                 # Extracted consignee company name
    cargo_description: str              # Extracted cargo text from B/L
    port_of_loading: str                # e.g., "Karachi"
    port_of_discharge: str              # e.g., "Rotterdam"
    document_discrepancies: list        # Cross-document mismatches

    # ── Sanctions Screening ──────────────────────────────────
    shipper_screening: dict             # Full sanctionscope response for shipper
    consignee_screening: dict           # Full sanctionscope response for consignee
    sanctions_risk: str                 # "GREEN" | "YELLOW" | "RED"

    # ── HS Classification ────────────────────────────────────
    hs_classification: dict             # Full tariffai response
    hs_code: str                        # e.g., "610510"
    hs_confidence: float                # 0.0 to 1.0

    # ── Risk Assessment ──────────────────────────────────────
    overall_risk: str                   # "GREEN" | "YELLOW" | "RED"
    risk_factors: Annotated[list, operator.add]  # Reducer: each node appends
    human_review_required: bool

    # ── Human Review (populated if pipeline pauses) ──────────
    human_decision: str                 # "approve" | "reject" | ""
    human_justification: str            # Written reason from compliance officer
    reviewed_by: str                    # Officer name / ID

    # ── Audit Trail ──────────────────────────────────────────
    audit_log: Annotated[list, operator.add]  # Reducer: each node appends

    # ── Pipeline Metadata ────────────────────────────────────
    pipeline_status: str                # "processing" | "awaiting_review" | "approved" | "blocked"
    compliance_report: dict             # Final compiled report
    started_at: str                     # ISO timestamp
    completed_at: str                   # ISO timestamp


# ═══════════════════════════════════════════════════════════════
# API Request / Response Models (Pydantic)
# ═══════════════════════════════════════════════════════════════

class ProcessRequest(BaseModel):
    """Request to process a trade document through the compliance pipeline."""
    document_path: str = Field(
        ...,
        description="Path to the trade document (PDF/image) to process",
        examples=["/Users/danyalwahdat/tradeguard/sample_docs/sample_bol.pdf"],
    )
    simulation_mode: bool = Field(
        default=False,
        description="If True, use mock extraction data instead of calling Azure",
    )


class ProcessDirectRequest(BaseModel):
    """
    Process pre-extracted trade data directly (skip document extraction).
    Useful for testing or when extraction is done externally.
    """
    shipper_name: str = Field(..., examples=["Pakistan Cotton Exports Ltd"])
    consignee_name: str = Field(..., examples=["Rotterdam Textiles BV"])
    cargo_description: str = Field(
        ...,
        examples=["500 cartons of mens cotton polo shirts, 100% cotton, knitted"],
    )
    port_of_loading: str = Field(default="", examples=["Karachi"])
    port_of_discharge: str = Field(default="", examples=["Rotterdam"])


class ReviewRequest(BaseModel):
    """Human review decision for a YELLOW-flagged shipment."""
    decision: Literal["approve", "reject"] = Field(
        ..., description="Compliance officer's decision"
    )
    justification: str = Field(
        ...,
        min_length=10,
        description="Written reason for the decision (required for audit trail)",
        examples=["Reviewed shipper history — legitimate textile exporter since 2018"],
    )
    reviewed_by: str = Field(
        ...,
        description="Name or ID of the reviewing compliance officer",
        examples=["Danyal Wahdat"],
    )


class PipelineStatusResponse(BaseModel):
    """Status check response for a document in the pipeline."""
    document_id: str
    pipeline_status: str
    overall_risk: str
    risk_factors: list[str]
    human_review_required: bool
    started_at: str
    completed_at: str | None = None


class ComplianceReportResponse(BaseModel):
    """Full compliance report for a processed document."""
    document_id: str
    pipeline_status: str
    overall_risk: str

    # Extraction summary
    shipper_name: str
    consignee_name: str
    cargo_description: str
    port_of_loading: str
    port_of_discharge: str
    document_discrepancies: list[dict]

    # Sanctions summary
    sanctions_risk: str
    shipper_screening_summary: dict
    consignee_screening_summary: dict

    # HS Classification summary
    hs_code: str | None
    hs_description: str | None
    hs_confidence: float

    # Decision
    risk_factors: list[str]
    human_review: dict | None  # decision, justification, reviewed_by

    # Audit
    audit_trail: list[dict]

    # Timing
    started_at: str
    completed_at: str | None
    processing_time_ms: float | None
