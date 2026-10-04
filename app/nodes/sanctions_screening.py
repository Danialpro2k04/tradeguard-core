"""
Node 3: Sanctions Screening

Calls the SanctionScope service (Week 3) to screen both the shipper
and consignee against OFAC, EU, and UN sanctions lists.

Makes TWO HTTP calls:
  1. POST /screen with shipper_name
  2. POST /screen with consignee_name

Then takes the WORST risk between the two:
  - If either is RED → sanctions_risk = RED
  - If either is YELLOW → sanctions_risk = YELLOW
  - Otherwise → sanctions_risk = GREEN
"""

import requests

from app.config import SANCTIONSCOPE_URL, SERVICE_TIMEOUT
from app.audit import create_audit_entry, get_previous_hash
from app.schemas import TradeComplianceState


RISK_PRIORITY = {"RED": 3, "YELLOW": 2, "GREEN": 1}


def _screen_entity(name: str, country: str = "") -> dict:
    """Call sanctionscope /screen for a single entity name."""
    try:
        payload = {"name": name}
        if country:
            payload["country"] = country

        response = requests.post(
            f"{SANCTIONSCOPE_URL}/screen",
            json=payload,
            timeout=SERVICE_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()

    except requests.exceptions.ConnectionError:
        return {
            "error": f"SanctionScope service unavailable at {SANCTIONSCOPE_URL}",
            "risk_level": "YELLOW",
            "query_name": name,
            "matches": [],
        }
    except Exception as e:
        return {
            "error": str(e)[:200],
            "risk_level": "YELLOW",
            "query_name": name,
            "matches": [],
        }


def sanctions_screening(state: TradeComplianceState) -> dict:
    """
    Node 3: Screen shipper and consignee against global sanctions lists.
    Takes the worst risk level between the two entities.
    """
    prev_hash = get_previous_hash(state.get("audit_log", []))

    shipper = state.get("shipper_name", "")
    consignee = state.get("consignee_name", "")

    # ── Screen shipper ──
    if shipper:
        shipper_result = _screen_entity(shipper)
    else:
        shipper_result = {
            "risk_level": "YELLOW",
            "query_name": "(missing)",
            "matches": [],
            "note": "Shipper name not extracted — cannot screen",
        }

    # ── Screen consignee ──
    if consignee:
        consignee_result = _screen_entity(consignee)
    else:
        consignee_result = {
            "risk_level": "YELLOW",
            "query_name": "(missing)",
            "matches": [],
            "note": "Consignee name not extracted — cannot screen",
        }

    # ── Determine worst risk ──
    shipper_risk = shipper_result.get("risk_level", "YELLOW")
    consignee_risk = consignee_result.get("risk_level", "YELLOW")
    worst_risk = max(
        [shipper_risk, consignee_risk],
        key=lambda r: RISK_PRIORITY.get(r, 0),
    )

    # ── Build risk factors ──
    risk_factors = []
    if shipper_risk == "RED":
        top_match = shipper_result.get("matches", [{}])[0] if shipper_result.get("matches") else {}
        risk_factors.append(
            f"SANCTIONS HIT: Shipper '{shipper}' matched sanctioned entity "
            f"'{top_match.get('matched_name', '?')}' (score: {top_match.get('combined_score', '?')})"
        )
    elif shipper_risk == "YELLOW":
        risk_factors.append(f"Sanctions: Shipper '{shipper}' flagged for possible match (YELLOW)")

    if consignee_risk == "RED":
        top_match = consignee_result.get("matches", [{}])[0] if consignee_result.get("matches") else {}
        risk_factors.append(
            f"SANCTIONS HIT: Consignee '{consignee}' matched sanctioned entity "
            f"'{top_match.get('matched_name', '?')}' (score: {top_match.get('combined_score', '?')})"
        )
    elif consignee_risk == "YELLOW":
        risk_factors.append(f"Sanctions: Consignee '{consignee}' flagged for possible match (YELLOW)")

    audit_entry = create_audit_entry(
        node_name="sanctions_screening",
        action=f"Screened shipper + consignee against OFAC/EU/UN sanctions lists",
        input_summary={"shipper": shipper[:50], "consignee": consignee[:50]},
        output_summary={
            "shipper_risk": shipper_risk,
            "consignee_risk": consignee_risk,
            "combined_risk": worst_risk,
            "shipper_matches": len(shipper_result.get("matches", [])),
            "consignee_matches": len(consignee_result.get("matches", [])),
        },
        previous_hash=prev_hash,
        risk_level=worst_risk,
    )

    return {
        "shipper_screening": shipper_result,
        "consignee_screening": consignee_result,
        "sanctions_risk": worst_risk,
        "risk_factors": risk_factors,
        "audit_log": [audit_entry],
    }
