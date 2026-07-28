"""SRL scientific contract primitives.

This package encodes the machine-checkable contracts that govern the
scientific IR and the shared artifact formats: canonical JSON encoding,
content-addressed object identity, strict numeric and timestamp policies,
portable artifact references, and the JSON Schema 2020-12 loader/validator.

Everything here is an *admission* contract. A green validation result means a
value satisfied the structural contract; it never means a scientific claim is
supported (see ``GOVERNANCE.md`` for the evidence rules).

Shared contract invariants
--------------------------
All contracts in this package share:

- **canonical JSON**: UTF-8, sorted keys, compact separators, ``allow_nan``
  is false, a final newline;
- **integer byte counts**: real integers ``>= 0``, never a ``bool``;
- **decimal strings** for precision-sensitive values (no exponent);
- **SHA-256 identity** over canonical bytes, prefixed ``sha256:``;
- **no absolute local paths** in portable artifacts;
- ``canonical_writes`` is ``0`` and ``grants_authority`` is ``false`` (safety
  consts, pinned in the envelope schema);
- schema dialect is JSON Schema 2020-12.
"""

from __future__ import annotations

from srl.contracts.artifact_refs import (
    ARTIFACT_REF_FAIL_REASON,
    ARTIFACT_REF_SCHEMA_VERSION,
    ArtifactRefError,
    validate_artifact_ref,
    validate_digest,
    validate_media_type,
    validate_portable_path,
)
from srl.contracts.canonical import (
    DECIMAL_STRING_PATTERN,
    CanonicalJSONError,
    DecimalPolicyError,
    decimal_to_str,
    dumps,
    loads,
)
from srl.contracts.canonical import (
    validate as canonical_validate,
)
from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError
from srl.contracts.ids import (
    IDENTITY_FAIL_REASON,
    OBJECT_ID_FIELD,
    OBJECT_ID_PREFIX,
    IdentityError,
    SelfHashError,
    is_self_referential,
    object_id,
    validate_object_id,
)
from srl.contracts.numbers import (
    NUMERIC_FAIL_REASON,
    NumericContractError,
    is_bool,
    reject_non_finite,
    validate_decimal_string,
    validate_integer,
    validate_integer_byte_count,
    validate_json_number,
)
from srl.contracts.schema import (
    SCHEMA_FAIL_REASON,
    ContractValidationError,
    SchemaError,
    list_schemas,
    load_schema,
    meta_validate_all,
    schema_file_map,
)
from srl.contracts.schema import (
    validate as schema_validate,
)
from srl.contracts.timestamps import (
    TIMESTAMP_FAIL_REASON,
    TimestampError,
)
from srl.contracts.timestamps import (
    normalize as normalize_timestamp,
)
from srl.contracts.timestamps import (
    validate as validate_timestamp,
)

__all__ = [
    "ARTIFACT_REF_FAIL_REASON",
    "ARTIFACT_REF_SCHEMA_VERSION",
    "CONTRACT_INVALID_FAIL_REASON",
    "DECIMAL_STRING_PATTERN",
    "IDENTITY_FAIL_REASON",
    "NUMERIC_FAIL_REASON",
    "OBJECT_ID_FIELD",
    "OBJECT_ID_PREFIX",
    "SCHEMA_FAIL_REASON",
    "TIMESTAMP_FAIL_REASON",
    "ArtifactRefError",
    "CanonicalJSONError",
    "ContractError",
    "ContractValidationError",
    "DecimalPolicyError",
    "IdentityError",
    "NumericContractError",
    "SchemaError",
    "SelfHashError",
    "TimestampError",
    "canonical_validate",
    "decimal_to_str",
    "dumps",
    "is_bool",
    "is_self_referential",
    "list_schemas",
    "load_schema",
    "loads",
    "meta_validate_all",
    "normalize_timestamp",
    "object_id",
    "reject_non_finite",
    "schema_file_map",
    "schema_validate",
    "validate_artifact_ref",
    "validate_decimal_string",
    "validate_digest",
    "validate_integer",
    "validate_integer_byte_count",
    "validate_json_number",
    "validate_media_type",
    "validate_object_id",
    "validate_portable_path",
    "validate_timestamp",
]
