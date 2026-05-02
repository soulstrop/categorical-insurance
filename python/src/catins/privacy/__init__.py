"""Privacy package: PII classification, tokenisation, and erasure.

Exposes the type-level PII marker (P2R.2) and the classification
report (P2R.6). Subsequent tickets add the tokenisation Protocol +
mock client (P2R.7) and the erasure operation + audit table (P2R.8).
"""

from catins.privacy.classification import (
    FieldClassification,
    ModelClassification,
    classify_models,
    classify_table,
)
from catins.privacy.erasure import (
    AUDIT_TABLE,
    ErasureResult,
    erase,
    init_audit_table,
)
from catins.privacy.pii import (
    PII,
    PIICategory,
    is_pii,
    non_pii_fields,
    pii_fields,
)
from catins.privacy.tokenisation import (
    MockTokenisationClient,
    TokenisationClient,
    detokenise_model,
    tokenise_model,
)

__all__ = [
    "AUDIT_TABLE",
    "ErasureResult",
    "FieldClassification",
    "MockTokenisationClient",
    "ModelClassification",
    "PII",
    "PIICategory",
    "TokenisationClient",
    "classify_models",
    "classify_table",
    "detokenise_model",
    "erase",
    "init_audit_table",
    "is_pii",
    "non_pii_fields",
    "pii_fields",
    "tokenise_model",
]
