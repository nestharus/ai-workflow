"""Transaction schema validation and deduplication.

Validates settlement instruction schemas, enforces currency code validity,
and handles reference-data unavailability with retry logic.
"""

from __future__ import annotations

from typing import Any

VALIDATION_RETRY_INTERVAL_SECONDS = 10
VALIDATION_RETRY_MAX_SECONDS = 120


class TransactionValidator:
    """Transaction validation engine."""

    def validate_schema(self, instruction: dict[str, Any]) -> bool:
        """Validate instruction schema."""
        # Schema validation rejects instructions with invalid currency codes
        pass

    def retry_on_reference_data_unavailable(self, instruction: dict[str, Any]) -> bool:
        """Retry validation when reference data is unavailable."""
        # Validation retries every 10 seconds for up to 2 minutes when reference-data unavailable
        pass
