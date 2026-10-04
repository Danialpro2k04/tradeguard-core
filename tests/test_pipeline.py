"""
TradeGuard Core Pipeline — End-to-End Tests

Tests the full LangGraph pipeline using simulation mode (no external
services required) and the /process/direct endpoint (pre-extracted data,
no Azure needed).
"""

from datetime import datetime, timezone

from app.graph import pipeline, build_graph
from app.audit import create_audit_entry, verify_audit_chain
from app.nodes.entity_extraction import entity_extraction
from app.nodes.risk_assessment import risk_assessment


# ═══════════════════════════════════════════════════════════════
# Test 1: Full pipeline in simulation mode (GREEN path)
# ═══════════════════════════════════════════════════════════════

def test_green_path_simulation():
    """
    A clean shipment with no sanctions matches should flow:
    document_intake → entity_extraction → sanctions_screening
    → hs_classification → risk_assessment → auto_approve → generate_report
    """
    graph = build_graph()

    initial_state = {
        "document_id": "TEST-GREEN-001",
        "raw_document_path": "simulation",
        "simulation_mode": True,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_status": "processing",
        "extraction_result": {},
        "shipper_name": "",
        "consignee_name": "",
        "cargo_description": "",
        "port_of_loading": "",
        "port_of_discharge": "",
        "document_discrepancies": [],
        "shipper_screening": {},
        "consignee_screening": {},
        "sanctions_risk": "",
        "hs_classification": {},
        "hs_code": "",
        "hs_confidence": 0.0,
        "overall_risk": "",
        "risk_factors": [],
        "human_review_required": False,
        "human_decision": "",
        "human_justification": "",
        "reviewed_by": "",
        "audit_log": [],
        "compliance_report": {},
        "completed_at": "",
    }

    config = {"configurable": {"thread_id": "test-green-001"}}
    result = graph.invoke(initial_state, config)

    # Verify the pipeline completed
    assert result["pipeline_status"] in ("approved", "awaiting_review", "blocked")
    assert result["document_id"] == "TEST-GREEN-001"
    assert result["shipper_name"] != ""  # Should be populated from simulation data
    assert result["consignee_name"] != ""
    assert result["cargo_description"] != ""

    # Verify audit trail exists and is non-empty
    assert len(result["audit_log"]) >= 5  # At minimum 5 nodes should have logged

    # Verify audit chain integrity
    is_valid, msg = verify_audit_chain(result["audit_log"])
    assert is_valid, f"Audit chain broken: {msg}"

    print(f"✅ GREEN path test passed — status: {result['pipeline_status']}")
    print(f"   Audit entries: {len(result['audit_log'])}")
    print(f"   HS code: {result.get('hs_code', 'N/A')}")
    print(f"   Audit chain: {msg}")


# ═══════════════════════════════════════════════════════════════
# Test 2: Entity extraction parsing
# ═══════════════════════════════════════════════════════════════

def test_entity_extraction_parsing():
    """Test that entity_extraction correctly parses the scanner output."""
    mock_state = {
        "extraction_result": {
            "status": "success",
            "extracted_data": {
                "page_0_bill_of_lading": {
                    "ShipperName": "ABC Trading Co",
                    "ConsigneeName": "XYZ Imports Ltd",
                    "CargoDescription": "500 CARTONS COTTON SHIRTS",
                    "PortOfLoading": "Karachi",
                    "PortOfDischarge": "Rotterdam",
                }
            },
            "discrepancies": [],
        },
        "audit_log": [],
    }

    result = entity_extraction(mock_state)

    assert result["shipper_name"] == "ABC Trading Co"
    assert result["consignee_name"] == "XYZ Imports Ltd"
    assert result["cargo_description"] == "500 CARTONS COTTON SHIRTS"
    assert result["port_of_loading"] == "Karachi"
    assert result["port_of_discharge"] == "Rotterdam"
    assert len(result["audit_log"]) == 1

    print("✅ Entity extraction parsing test passed")


# ═══════════════════════════════════════════════════════════════
# Test 3: Entity extraction with missing fields
# ═══════════════════════════════════════════════════════════════

def test_entity_extraction_missing_fields():
    """Missing fields should generate risk factors."""
    mock_state = {
        "extraction_result": {
            "status": "success",
            "extracted_data": {
                "page_0_bill_of_lading": {
                    "ShipperName": "ABC Trading Co",
                    # Missing ConsigneeName and CargoDescription
                    "PortOfLoading": "Karachi",
                }
            },
            "discrepancies": [],
        },
        "audit_log": [],
    }

    result = entity_extraction(mock_state)

    assert result["shipper_name"] == "ABC Trading Co"
    assert result["consignee_name"] == ""  # Missing
    assert result["cargo_description"] == ""  # Missing
    assert len(result["risk_factors"]) > 0  # Should flag missing fields
    assert any("Missing critical fields" in rf for rf in result["risk_factors"])

    print("✅ Missing fields test passed — risk factors generated")


# ═══════════════════════════════════════════════════════════════
# Test 4: Risk assessment logic
# ═══════════════════════════════════════════════════════════════

def test_risk_assessment_red():
    """RED sanctions should always produce RED overall risk."""
    mock_state = {
        "sanctions_risk": "RED",
        "hs_confidence": 0.95,
        "hs_code": "610510",
        "document_discrepancies": [],
        "risk_factors": ["SANCTIONS HIT: Shipper matched sanctioned entity"],
        "shipper_name": "Test Corp",
        "consignee_name": "Test Buyer",
        "audit_log": [],
    }

    result = risk_assessment(mock_state)
    assert result["overall_risk"] == "RED"
    assert result["human_review_required"] is True

    print("✅ RED risk assessment test passed")


def test_risk_assessment_green():
    """Clean sanctions + high HS confidence = GREEN."""
    mock_state = {
        "sanctions_risk": "GREEN",
        "hs_confidence": 0.95,
        "hs_code": "610510",
        "document_discrepancies": [],
        "risk_factors": [],
        "shipper_name": "Test Corp",
        "consignee_name": "Test Buyer",
        "audit_log": [],
    }

    result = risk_assessment(mock_state)
    assert result["overall_risk"] == "GREEN"
    assert result["human_review_required"] is False

    print("✅ GREEN risk assessment test passed")


def test_risk_assessment_yellow_low_confidence():
    """Low HS confidence should trigger YELLOW."""
    mock_state = {
        "sanctions_risk": "GREEN",
        "hs_confidence": 0.45,
        "hs_code": "620462",
        "document_discrepancies": [],
        "risk_factors": [],
        "shipper_name": "Test Corp",
        "consignee_name": "Test Buyer",
        "audit_log": [],
    }

    result = risk_assessment(mock_state)
    assert result["overall_risk"] == "YELLOW"
    assert result["human_review_required"] is True

    print("✅ YELLOW (low confidence) risk assessment test passed")


# ═══════════════════════════════════════════════════════════════
# Test 5: Audit chain integrity
# ═══════════════════════════════════════════════════════════════

def test_audit_chain_integrity():
    """Hash chain should verify correctly for valid entries."""
    entries = []
    for i in range(5):
        prev_hash = entries[-1]["hash"] if entries else ""
        entry = create_audit_entry(
            node_name=f"node_{i}",
            action=f"Test action {i}",
            input_summary={"step": i},
            output_summary={"result": f"output_{i}"},
            previous_hash=prev_hash,
        )
        entries.append(entry)

    is_valid, msg = verify_audit_chain(entries)
    assert is_valid, f"Chain should be valid: {msg}"

    print(f"✅ Audit chain integrity test passed — {msg}")


def test_audit_chain_tamper_detection():
    """Modifying a past entry should break the chain."""
    entries = []
    for i in range(5):
        prev_hash = entries[-1]["hash"] if entries else ""
        entry = create_audit_entry(
            node_name=f"node_{i}",
            action=f"Test action {i}",
            input_summary={"step": i},
            output_summary={"result": f"output_{i}"},
            previous_hash=prev_hash,
        )
        entries.append(entry)

    # Tamper with entry 2
    entries[2]["action"] = "TAMPERED ACTION"

    is_valid, msg = verify_audit_chain(entries)
    assert not is_valid, "Chain should be broken after tampering"
    assert "entry 2" in msg

    print(f"✅ Audit chain tamper detection test passed — {msg}")


# ═══════════════════════════════════════════════════════════════
# Run all tests
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("TradeGuard Core Pipeline — Test Suite")
    print("=" * 60 + "\n")

    test_entity_extraction_parsing()
    test_entity_extraction_missing_fields()
    test_risk_assessment_red()
    test_risk_assessment_green()
    test_risk_assessment_yellow_low_confidence()
    test_audit_chain_integrity()
    test_audit_chain_tamper_detection()
    test_green_path_simulation()

    print("\n" + "=" * 60)
    print("All tests passed ✅")
    print("=" * 60)
