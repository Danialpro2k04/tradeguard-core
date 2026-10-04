"""
TradeGuard Core Pipeline — Hash-Chained Audit Trail

Every node in the pipeline calls create_audit_entry() to record what
it did, what it received, and what it produced. Each entry includes
a SHA-256 hash of the previous entry, creating a tamper-evident chain.

If anyone modifies a past entry, every subsequent hash breaks.
This is legally required for trade compliance audit trails.

Chain structure:
  Entry 0: hash = sha256("" + entry_0_json)
  Entry 1: hash = sha256(entry_0.hash + entry_1_json)
  Entry 2: hash = sha256(entry_1.hash + entry_2_json)
"""

import hashlib
import json
from datetime import datetime, timezone


def create_audit_entry(
    node_name: str,
    action: str,
    input_summary: dict | str,
    output_summary: dict | str,
    previous_hash: str = "",
    confidence: float | None = None,
    risk_level: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """
    Create a single hash-chained audit entry.

    Args:
        node_name: Which pipeline node produced this entry (e.g., "sanctions_screening")
        action: What the node did (e.g., "Screened shipper against OFAC/EU/UN lists")
        input_summary: What the node received (truncated for readability)
        output_summary: What the node produced
        previous_hash: Hash from the previous audit entry (empty string for first entry)
        confidence: Optional confidence score (0-1) for the operation
        risk_level: Optional risk level produced by this node
        metadata: Any extra context to attach

    Returns:
        A dict representing one audit log entry with its chain hash
    """
    entry_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "node": node_name,
        "action": action,
        "input": input_summary,
        "output": output_summary,
    }

    if confidence is not None:
        entry_data["confidence"] = confidence
    if risk_level is not None:
        entry_data["risk_level"] = risk_level
    if metadata:
        entry_data["metadata"] = metadata

    # Build the hash chain:
    # hash = SHA256(previous_hash + JSON(this_entry))
    entry_json = json.dumps(entry_data, sort_keys=True, default=str)
    chain_input = previous_hash + entry_json
    entry_data["hash"] = hashlib.sha256(chain_input.encode()).hexdigest()

    return entry_data


def get_previous_hash(audit_log: list[dict]) -> str:
    """Extract the hash from the last entry in the audit log, or empty string if log is empty."""
    if audit_log:
        return audit_log[-1].get("hash", "")
    return ""


def verify_audit_chain(audit_log: list[dict]) -> tuple[bool, str]:
    """
    Verify the integrity of the entire audit chain.

    Returns:
        (is_valid, message): True if chain is intact, False with explanation if broken
    """
    prev_hash = ""
    for i, entry in enumerate(audit_log):
        stored_hash = entry.get("hash", "")
        # Rebuild the entry without the hash field to verify
        entry_copy = {k: v for k, v in entry.items() if k != "hash"}
        entry_json = json.dumps(entry_copy, sort_keys=True, default=str)
        expected_hash = hashlib.sha256((prev_hash + entry_json).encode()).hexdigest()

        if stored_hash != expected_hash:
            return False, f"Chain broken at entry {i} (node: {entry.get('node', '?')})"
        prev_hash = stored_hash

    return True, f"Chain intact — {len(audit_log)} entries verified"
