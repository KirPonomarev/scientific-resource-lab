"""Schema loader and validator for SRL contract schemas.

This module is the single entry point for working with the packaged JSON
Schema 2020-12 documents (see ``src/srl/contracts/schemas/v1/``). It does
three things:

1. **Load** a packaged schema by logical name (e.g. ``"ArtifactRef"``) via
   :func:`importlib.resources`, so the schema a running program uses is the
   schema that shipped with the installed wheel — never a loose local file.
2. **Meta-validate** every shipped schema against the JSON Schema 2020-12
   meta-schema, the first time it is loaded. A schema that does not conform
   to the 2020-12 dialect cannot be used; this catches a malformed or
   dialect-drifted schema before it silently accepts bad data.
3. **Validate** a JSON instance against a named schema, raising a typed
   :class:`ContractValidationError` that carries the failing JSON path so a
   caller can point at the exact field that failed.

Why a real validator (not hand-rolled)
--------------------------------------
The scientific contracts layer depends on schema correctness for identity and
content-addressing. A hand-rolled validator would have to track the 2020-12
keyword set, subschema composition, and error path accumulation itself; the
``jsonschema`` library already does this correctly and is the reference
implementation. See ``docs/adr/0002-jsonschema-library.md`` for the
decision record.

Lazy meta-schema
----------------
The 2020-12 meta-schema is fetched once via ``jsonschema``'s registry and
memoized, so the cost is paid on first load only.
"""

from __future__ import annotations

import json
from functools import cache, lru_cache
from importlib import resources
from typing import Any, Final

from jsonschema import Draft202012Validator

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

# Logical schema-name suffixes the loader understands. The packaged files live
# under src/srl/contracts/schemas/v1/. A name like "ArtifactRef" maps to the
# file "artifact-ref.json" (kebab-case). The mapping is explicit so a typo in
# a schema name fails loudly instead of resolving to a surprising file.
_SCHEMA_PACKAGE: Final[str] = "srl.contracts.schemas.v1"
_SCHEMA_NAME_TO_FILE: Final[dict[str, str]] = {
    "ArtifactRef": "artifact-ref.json",
    "ScientificObjectEnvelope": "scientific-object-envelope.json",
    "GateReceipt": "gate-receipt.json",
}

# Typed fail reason for schema-level failures (meta-validation + instance
# validation). Both are structural contract failures.
SCHEMA_FAIL_REASON: Final[str] = CONTRACT_INVALID_FAIL_REASON


class SchemaError(ContractError):
    """Raised when a schema document cannot be loaded or meta-validated.

    Covers: unknown schema name, missing packaged file, malformed JSON, and
    failure of the schema to conform to the 2020-12 meta-schema.
    """


class ContractValidationError(ContractError):
    """Raised when a JSON instance fails validation against a named schema.

    Attributes
    ----------
    schema_name:
        The logical schema name the instance was validated against.
    json_path:
        The JSON pointer (RFC 6901 style, e.g. ``/payload/digest``) to the
        failing element, when the underlying validator produced one.
    validator:
        The JSON Schema keyword that failed (e.g. ``"pattern"``, ``"type"``).
    """

    def __init__(
        self,
        message: str,
        *,
        schema_name: str = "",
        json_path: str = "",
        validator: str = "",
        fail_reason: str = SCHEMA_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)
        self.schema_name: str = schema_name
        self.json_path: str = json_path
        self.validator: str = validator


@lru_cache(maxsize=1)
def _meta_validator() -> Draft202012Validator:
    """Return the cached 2020-12 meta-schema validator.

    The meta-schema is fetched from ``jsonschema``'s bundled registry (the
    ``jsonschema-specifications`` distribution) so the check works offline.
    Memoized so the cost is paid once per process.
    """
    return Draft202012Validator(Draft202012Validator.META_SCHEMA)


@cache
def _load_and_metavalidate(name: str) -> dict[str, Any]:
    """Load and meta-validate the packaged schema for ``name`` (memoized).

    The memoization is keyed by logical name; the schema is read once and
    meta-validated once. Subsequent :func:`load_schema` / :func:`validate`
    calls reuse the cached dict.
    """
    filename = _SCHEMA_NAME_TO_FILE.get(name)
    if filename is None:
        msg = f"unknown schema name {name!r}; known names: {sorted(_SCHEMA_NAME_TO_FILE)}"
        raise SchemaError(msg)
    try:
        raw = resources.files(_SCHEMA_PACKAGE).joinpath(filename).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError) as exc:
        msg = f"could not read packaged schema {name!r} ({filename}): {exc}"
        raise SchemaError(msg) from exc
    try:
        schema = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"packaged schema {name!r} ({filename}) is not valid JSON: {exc}"
        raise SchemaError(msg) from exc
    if not isinstance(schema, dict):
        msg = (
            f"packaged schema {name!r} ({filename}) must be a JSON object, "
            f"got {type(schema).__name__}"
        )
        raise SchemaError(msg)
    # Meta-validate before handing the schema out: a malformed schema must not
    # silently accept bad data.
    meta_errors = sorted(_meta_validator().iter_errors(schema), key=lambda e: e.path)
    if meta_errors:
        first = meta_errors[0]
        msg = (
            f"packaged schema {name!r} ({filename}) fails 2020-12 meta-validation "
            f"at {first.json_path!r}: {first.message}"
        )
        raise SchemaError(msg)
    return schema


def load_schema(name: str) -> dict[str, Any]:
    """Load and return the packaged schema for ``name``.

    Parameters
    ----------
    name:
        Logical schema name, one of ``"ArtifactRef"``,
        ``"ScientificObjectEnvelope"``, ``"GateReceipt"``.

    Returns
    -------
    dict[str, Any]
        The parsed schema document. The returned dict is the cached parsed
        form; callers must not mutate it.

    Raises
    ------
    SchemaError
        If ``name`` is unknown, the packaged file is missing/unreadable, the
        JSON is malformed, or the schema fails 2020-12 meta-validation.

    Notes
    -----
    The schema is meta-validated on first load and memoized. Repeated calls
    return the same dict without re-reading or re-validating.
    """
    return _load_and_metavalidate(name)


def list_schemas() -> list[str]:
    """Return the sorted list of known (loadable) schema names."""
    return sorted(_SCHEMA_NAME_TO_FILE)


def schema_file_map() -> dict[str, str]:
    """Return a copy of the logical-name -> packaged-filename map.

    Exposed so the meta-validation check can assert every ``.json`` file on
    disk corresponds to a known schema (no orphan files). The returned dict is
    a shallow copy; callers may mutate it freely.
    """
    return dict(_SCHEMA_NAME_TO_FILE)


def validate(instance: Any, schema_name: str) -> None:
    """Validate ``instance`` against the named packaged schema.

    Parameters
    ----------
    instance:
        The JSON value to validate.
    schema_name:
        Logical schema name (see :func:`load_schema`).

    Raises
    ------
    ContractValidationError
        If ``instance`` does not satisfy the schema. Carries the failing JSON
        path and the keyword that failed.
    SchemaError
        If the schema itself cannot be loaded/meta-validated (propagated from
        :func:`load_schema`).
    """
    schema = load_schema(schema_name)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        msg = (
            f"instance failed validation against {schema_name!r} at "
            f"{first.json_path!r}: {first.message}"
        )
        raise ContractValidationError(
            msg,
            schema_name=schema_name,
            json_path=first.json_path,
            validator=first.validator,
        )


def meta_validate_all() -> dict[str, str]:
    """Meta-validate every shipped schema and return a name->"$id" map.

    Intended for the schema-meta-validate check script and CI: it loads every
    known schema (each load meta-validates) and returns the ``$id`` of each as
    evidence the schema is well-formed and unique-addressed.

    Raises
    ------
    SchemaError
        If any schema fails meta-validation (propagated from
        :func:`load_schema`).
    """
    out: dict[str, str] = {}
    for name in list_schemas():
        schema = load_schema(name)
        sid = schema.get("$id", "")
        if not isinstance(sid, str) or not sid:
            msg = f"schema {name!r} is missing a string $id"
            raise SchemaError(msg)
        out[name] = sid
    # Uniqueness: two schemas must not share an $id.
    seen: dict[str, str] = {}
    for name, sid in out.items():
        if sid in seen:
            msg = f"schemas {seen[sid]!r} and {name!r} share $id {sid!r}"
            raise SchemaError(msg)
        seen[sid] = name
    return out


__all__ = [
    "SCHEMA_FAIL_REASON",
    "ContractValidationError",
    "SchemaError",
    "list_schemas",
    "load_schema",
    "meta_validate_all",
    "schema_file_map",
    "validate",
]
