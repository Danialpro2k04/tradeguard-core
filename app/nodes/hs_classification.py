"""
Node 4: HS Classification

Calls the TariffAI service (Week 4) to classify the cargo description
into a 6-digit Harmonized System tariff code.

IMPORTANT: If sanctions_risk is RED, this node SKIPS the LLM call
entirely. There's no point spending tokens classifying cargo for a
shipment that's going to be blocked. This is the "fail fast" principle.
"""

import requests

from app.config import TARIFFAI_URL, SERVICE_TIMEOUT
from app.audit import create_audit_entry, get_previous_hash
from app.schemas import TradeComplianceState


def hs_classification(state: TradeComplianceState) -> dict:
    """
    Node 4: Classify cargo description into a 6-digit HS code via TariffAI.
    Skips the call entirely if sanctions_risk is RED (fail fast).
    """
    prev_hash = get_previous_hash(state.get("audit_log", []))

    # ── Fail fast: skip if sanctions already RED ──
    if state.get("sanctions_risk") == "RED":
        audit_entry = create_audit_entry(
            node_name="hs_classification",
            action="SKIPPED — sanctions screening returned RED (shipment will be blocked)",
            input_summary={"cargo": state.get("cargo_description", "")[:80]},
            output_summary={"skipped": True, "reason": "sanctions_risk == RED"},
            previous_hash=prev_hash,
        )
        return {
            "hs_classification": {"skipped": True, "reason": "sanctions_risk == RED"},
            "hs_code": "",
            "hs_confidence": 0.0,
            "audit_log": [audit_entry],
        }

    cargo = state.get("cargo_description", "")
    if not cargo or len(cargo.strip()) < 3:
        audit_entry = create_audit_entry(
            node_name="hs_classification",
            action="SKIPPED — cargo description is empty or too short",
            input_summary={"cargo": cargo},
            output_summary={"skipped": True, "reason": "empty cargo description"},
            previous_hash=prev_hash,
        )
        return {
            "hs_classification": {"skipped": True, "reason": "empty cargo"},
            "hs_code": "",
            "hs_confidence": 0.0,
            "risk_factors": ["HS classification skipped: no cargo description extracted"],
            "audit_log": [audit_entry],
        }

    # ── Call TariffAI ──
    try:
        response = requests.post(
            f"{TARIFFAI_URL}/classify",
            json={"description": cargo},
            timeout=SERVICE_TIMEOUT,
        )
        response.raise_for_status()
        result = response.json()

        classification = result.get("result", {})
        hs_code = classification.get("primary_code", "")
        confidence = classification.get("confidence", 0.0)
        is_ambiguous = classification.get("is_ambiguous", False)

        risk_factors = []
        if is_ambiguous:
            risk_factors.append(
                f"HS classification ambiguous: code {hs_code} "
                f"with {confidence:.0%} confidence (below 70% threshold)"
            )

        audit_entry = create_audit_entry(
            node_name="hs_classification",
            action=f"Classified cargo into HS code {hs_code}",
            input_summary={"cargo": cargo[:80]},
            output_summary={
                "hs_code": hs_code,
                "description": classification.get("primary_description", "")[:60],
                "confidence": confidence,
                "is_ambiguous": is_ambiguous,
                "alternatives": len(classification.get("alternative_codes", [])),
            },
            previous_hash=prev_hash,
            confidence=confidence,
        )

        return {
            "hs_classification": result,
            "hs_code": hs_code,
            "hs_confidence": confidence,
            "risk_factors": risk_factors,
            "audit_log": [audit_entry],
        }

    except requests.exceptions.ConnectionError:
        audit_entry = create_audit_entry(
            node_name="hs_classification",
            action=f"FAILED — TariffAI service unavailable at {TARIFFAI_URL}",
            input_summary={"cargo": cargo[:80]},
            output_summary={"error": "service unavailable"},
            previous_hash=prev_hash,
            risk_level="YELLOW",
        )
        return {
            "hs_classification": {"error": "TariffAI unavailable"},
            "hs_code": "",
            "hs_confidence": 0.0,
            "risk_factors": ["HS classification failed: TariffAI service unavailable"],
            "audit_log": [audit_entry],
        }
    except Exception as e:
        audit_entry = create_audit_entry(
            node_name="hs_classification",
            action=f"FAILED — {str(e)[:200]}",
            input_summary={"cargo": cargo[:80]},
            output_summary={"error": str(e)[:200]},
            previous_hash=prev_hash,
            risk_level="YELLOW",
        )
        return {
            "hs_classification": {"error": str(e)[:200]},
            "hs_code": "",
            "hs_confidence": 0.0,
            "risk_factors": [f"HS classification error: {str(e)[:100]}"],
            "audit_log": [audit_entry],
        }
