"""Privacy package: PII classification, tokenisation, and erasure.

Currently exposes the type-level PII marker (P2R.2). Subsequent
tickets add the classification report (P2R.6), tokenisation Protocol +
mock client (P2R.7), and erasure operation + audit table (P2R.8).
"""

from catins.privacy.pii import (
    PII,
    PIICategory,
    is_pii,
    non_pii_fields,
    pii_fields,
)

__all__ = [
    "PII",
    "PIICategory",
    "is_pii",
    "non_pii_fields",
    "pii_fields",
]
