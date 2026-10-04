"""
TradeGuard Core Pipeline — Configuration

All service URLs and compliance thresholds live here.
Values are loaded from environment variables with sensible defaults.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ═══════════════════════════════════════════════════════════════
# Month 1 Microservice URLs
# Each Month 1 engine runs as its own FastAPI service.
# The core pipeline calls them via HTTP.
# ═══════════════════════════════════════════════════════════════

# Week 1-2: Document extraction (Azure Document Intelligence)
DOCUMENT_SCANNER_URL = os.getenv(
    "DOCUMENT_SCANNER_URL", "http://localhost:8000"
)

# Week 3: Sanctions screening (Qdrant + fuzzy/semantic matching)
SANCTIONSCOPE_URL = os.getenv(
    "SANCTIONSCOPE_URL", "http://localhost:8001"
)

# Week 4: HS tariff classification (Qdrant + BM25 + Gemini LLM)
TARIFFAI_URL = os.getenv(
    "TARIFFAI_URL", "http://localhost:8004"
)

# ═══════════════════════════════════════════════════════════════
# Compliance Thresholds
# These define when the pipeline auto-clears vs flags for review.
# ═══════════════════════════════════════════════════════════════

# Sanctions: if combined_score >= this, it's RED (blocked)
SANCTIONS_RED_THRESHOLD = float(os.getenv("SANCTIONS_RED_THRESHOLD", "0.90"))

# Sanctions: if combined_score >= this but < RED, it's YELLOW (review)
SANCTIONS_YELLOW_THRESHOLD = float(os.getenv("SANCTIONS_YELLOW_THRESHOLD", "0.65"))

# HS Classification: if confidence < this, flag for review
HS_CONFIDENCE_THRESHOLD = float(os.getenv("HS_CONFIDENCE_THRESHOLD", "0.70"))

# ═══════════════════════════════════════════════════════════════
# Pipeline Settings
# ═══════════════════════════════════════════════════════════════

# Enable simulation mode for testing without live services
# When True, uses pre-built sample data instead of calling services
SIMULATION_MODE = os.getenv("SIMULATION_MODE", "false").lower() == "true"

# HTTP timeout for service calls (seconds)
SERVICE_TIMEOUT = int(os.getenv("SERVICE_TIMEOUT", "30"))

# Pipeline port
PIPELINE_PORT = int(os.getenv("PIPELINE_PORT", "8005"))
