"""
Node 2: Entity Extraction

Parses the raw extraction_result from freight_document_scanner to pull out
the specific fields the pipeline needs: shipper name, consignee name,
cargo description, ports, and any cross-document discrepancies.

This node does NOT call any external service — it's pure Python parsing.
It bridges the gap between the scanner's raw output format and the
structured fields the rest of the pipeline expects.
"""

from app.audit import create_audit_entry, get_previous_hash
from app.schemas import TradeComplianceState


def entity_extraction(state: TradeComplianceState) -> dict:
    """
    Node 2: Parse the extraction result to populate shipper, consignee,
    cargo description, ports, and discrepancies in the pipeline state.
    """
    prev_hash = get_previous_hash(state.get("audit_log", []))
    extraction = state.get("extraction_result", {})

    # ── Direct input: data already pre-filled, just log and pass through ──
    if extraction.get("status") == "direct_input":
        audit_entry = create_audit_entry(
            node_name="entity_extraction",
            action="Skipped extraction parsing — entities provided directly",
            input_summary={"method": "direct_input"},
            output_summary={
                "shipper": state.get("shipper_name", "")[:50],
                "consignee": state.get("consignee_name", "")[:50],
                "cargo": state.get("cargo_description", "")[:80],
            },
            previous_hash=prev_hash,
        )
        return {"audit_log": [audit_entry]}

    # Default values
    shipper = ""
    consignee = ""
    cargo = ""
    pol = ""
    pod = ""
    discrepancies = []

    if extraction.get("status") == "success":
        extracted_data = extraction.get("extracted_data", {})

        # Walk through all extracted pages looking for B/L fields
        for page_key, fields in extracted_data.items():
            if "bill_of_lading" in page_key.lower():
                # Try multiple field name variants (Azure models vary)
                shipper = (
                    fields.get("ShipperName")
                    or fields.get("Shipper Name")
                    or fields.get("shipper_name")
                    or shipper
                )
                consignee = (
                    fields.get("ConsigneeName")
                    or fields.get("Consignee Name")
                    or fields.get("consignee_name")
                    or consignee
                )
                cargo = (
                    fields.get("CargoDescription")
                    or fields.get("Cargo Description")
                    or fields.get("cargo_description")
                    or fields.get("Description of Goods")
                    or cargo
                )
                pol = (
                    fields.get("PortOfLoading")
                    or fields.get("Port of Loading")
                    or fields.get("port_of_loading")
                    or pol
                )
                pod = (
                    fields.get("PortOfDischarge")
                    or fields.get("Port of Discharge")
                    or fields.get("port_of_discharge")
                    or pod
                )

        # Collect cross-document discrepancies flagged by the scanner
        discrepancies = extraction.get("discrepancies", [])

    # Build risk factors from discrepancies
    risk_factors = []
    if discrepancies:
        risk_factors.append(
            f"Document discrepancies detected: {len(discrepancies)} issue(s)"
        )

    # Build risk factors from missing critical fields
    missing = []
    if not shipper:
        missing.append("shipper_name")
    if not consignee:
        missing.append("consignee_name")
    if not cargo:
        missing.append("cargo_description")
    if missing:
        risk_factors.append(f"Missing critical fields: {', '.join(missing)}")

    audit_entry = create_audit_entry(
        node_name="entity_extraction",
        action="Parsed extraction result into structured trade entities",
        input_summary={"pages_analyzed": len(extraction.get("extracted_data", {}))},
        output_summary={
            "shipper": shipper[:50] if shipper else "(missing)",
            "consignee": consignee[:50] if consignee else "(missing)",
            "cargo": cargo[:80] if cargo else "(missing)",
            "ports": f"{pol} → {pod}",
            "discrepancies": len(discrepancies),
        },
        previous_hash=prev_hash,
    )

    return {
        "shipper_name": shipper,
        "consignee_name": consignee,
        "cargo_description": cargo,
        "port_of_loading": pol,
        "port_of_discharge": pod,
        "document_discrepancies": discrepancies,
        "risk_factors": risk_factors,
        "audit_log": [audit_entry],
    }
