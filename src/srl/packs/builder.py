"""Build a deterministic ResourcePackManifest/v1 from a pack spec and tree.

:func:`build_pack` turns a declarative pack spec and a directory of files into a
validated :class:`~srl.packs.manifest.ResourcePackManifest` and a tree path. The
manifest is deterministic: the same spec and the same file tree produce the same
canonical manifest bytes, so independent agents can compare manifests by hash.

Determinism guarantees
----------------------
- ``tree_sha256`` is computed by the canonical tree hashing from
  :mod:`srl.packs.manifest`.
- ``source_sha256`` is computed from the canonical encoding of the source
  metadata (``url`` and ``commit``), so identical source declarations hash the
  same.
- ``lock_sha256`` is computed from a ``lock.json`` file if present, otherwise
  from the empty byte string (the "absent" sentinel).
- ``license.texts_sha256`` is computed from ``LICENSE.txt`` if present,
  otherwise from a deterministic default license text for the declared SPDX.
- ``created_utc`` defaults to the epoch ``1970-01-01T00:00:00Z`` so the manifest
  is byte-stable across builds; callers may supply a timestamp via the spec.

Spec shape
----------
Required keys:

- ``name``: human-readable pack name.
- ``version``: pack version string.
- ``capability_profiles``: list of SRL capability profile names.
- ``entrypoints``: list of ``{"entrypoint_id": str, "kind": "python_module",
  "ref": str}`` objects.
- ``source``: ``{"url": str | None, "commit": str | None}``.
- ``license``: ``{"spdx": str}``.

Optional keys (with deterministic defaults):

- ``pack_id``: defaults to ``"{name}.{version}"`` with spaces normalized to ``_``.
- ``platforms``: defaults to all four supported os/arch combinations.
- ``sbom_sha256``: defaults to ``None``.
- ``probes``: defaults to ``{"runtime_probe": first_entrypoint_id,
  "actual_compute_probe": first_entrypoint_id}``. If two or more entrypoints
  are supplied, ``actual_compute_probe`` defaults to the second entrypoint.
- ``created_utc``: defaults to ``"1970-01-01T00:00:00Z"``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Final

from srl.contracts.canonical import dumps
from srl.packs.manifest import (
    LICENSE_ALLOWLIST,
    LICENSE_INCOMPATIBLE_PREFIXES,
    LicenseError,
    PackManifestError,
    ResourcePackManifest,
    build_manifest,
    compute_tree_sha256,
)
from srl.planning.profiles import PROFILE_NAMES

# Sentinel for absent source/lock content: sha256 of the empty byte string.
# Using the real empty-string digest makes the absent value a valid content
# digest, avoiding a special-case marker that would break canonical validators.
_EMPTY_SHA256: Final[str] = "sha256:" + hashlib.sha256(b"").hexdigest()

# Default reproducible build timestamp. The manifest stores it as a string; a
# fixed value keeps the canonical manifest bytes stable across builds.
_DEFAULT_CREATED_UTC: Final[str] = "1970-01-01T00:00:00Z"

# Default supported platforms, in canonical sorted order.
_DEFAULT_PLATFORMS: Final[list[dict[str, str | None]]] = [
    {"os": "linux", "arch": "x86_64", "abi": None},
    {"os": "linux", "arch": "arm64", "abi": None},
    {"os": "macos", "arch": "x86_64", "abi": None},
    {"os": "macos", "arch": "arm64", "abi": None},
]


class BuilderError(PackManifestError):
    """Raised when a pack spec or tree cannot be built into a manifest."""


# License text templates for common permissive licenses used when the workdir
# does not contain a LICENSE.txt file. The text is deterministic so the same
# SPDX always yields the same license.texts_sha256.
_DEFAULT_LICENSE_TEMPLATES: Final[dict[str, str]] = {
    "MIT": (
        "MIT License\n\n"
        "Permission is hereby granted, free of charge, to any person obtaining a copy\n"
        "of this software and associated documentation files (the “Software”), to deal\n"
        "in the Software without restriction, including without limitation the rights\n"
        "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell\n"
        "copies of the Software, and to permit persons to whom the Software is furnished\n"
        "to do so, subject to the following conditions:\n\n"
        "The above copyright notice and this permission notice shall be included in all\n"
        "copies or substantial portions of the Software.\n"
    ),
    "Apache-2.0": (
        "Apache License, Version 2.0\n\n"
        "Licensed under the Apache License, Version 2.0 (the “License”); you may not\n"
        "use this file except in compliance with the License. You may obtain a copy of\n"
        "the License at http://www.apache.org/licenses/LICENSE-2.0\n\n"
        "Unless required by applicable law or agreed to in writing, software distributed\n"
        "under the License is distributed on an “AS IS” BASIS, WITHOUT WARRANTIES OR\n"
        "CONDITIONS OF ANY KIND, either express or implied. See the License for the\n"
        "specific language governing permissions and limitations under the License.\n"
    ),
    "BSD-3-Clause": (
        "BSD 3-Clause License\n\n"
        "Redistribution and use in source and binary forms, with or without\n"
        "modification, are permitted provided that the following conditions are met:\n\n"
        "1. Redistributions of source code must retain the above copyright notice, this\n"
        "   list of conditions and the following disclaimer.\n"
        "2. Redistributions in binary form must reproduce the above copyright notice,\n"
        "   this list of conditions and the following disclaimer in the documentation\n"
        "   and/or other materials provided with the distribution.\n"
        "3. Neither the name of the copyright holder nor the names of its contributors\n"
        "   may be used to endorse or promote products derived from this software without\n"
        "   specific prior written permission.\n"
    ),
}


def _sha256_bytes(data: bytes) -> str:
    """Return ``sha256:<64 hex>`` for ``data``."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _sha256_canonical(obj: Any) -> str:
    """Return ``sha256:<64 hex>`` for the canonical JSON encoding of ``obj``."""
    return _sha256_bytes(dumps(obj))


def _require_str(value: Any, field: str) -> str:
    """Validate a required non-empty string field in the spec."""
    if not isinstance(value, str) or value == "":
        msg = f"spec field {field!r} must be a non-empty string, got {value!r}"
        raise BuilderError(msg)
    return value


def _require_list(value: Any, field: str) -> list[Any]:
    """Validate a required list field in the spec."""
    if not isinstance(value, list):
        msg = f"spec field {field!r} must be a list, got {type(value).__name__}"
        raise BuilderError(msg)
    return value


def _require_dict(value: Any, field: str) -> dict[str, Any]:
    """Validate a required dict field in the spec."""
    if not isinstance(value, dict):
        msg = f"spec field {field!r} must be an object, got {type(value).__name__}"
        raise BuilderError(msg)
    return value


def _optional_str(value: Any, field: str) -> str | None:
    """Validate an optional nullable string field in the spec."""
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"spec field {field!r} must be a string or null, got {type(value).__name__}"
        raise BuilderError(msg)
    return value


def _derive_pack_id(name: str, version: str) -> str:
    """Derive a deterministic pack_id from ``name`` and ``version``."""
    safe_name = name.replace(" ", "_").replace("/", "_").lower()
    return f"{safe_name}.{version}"


def _validate_profiles(profiles: list[Any]) -> list[str]:
    """Validate capability profile names and return a list of strings."""
    validated: list[str] = []
    for i, item in enumerate(profiles):
        if not isinstance(item, str) or item == "":
            msg = f"capability_profiles[{i}] must be a non-empty string, got {item!r}"
            raise BuilderError(msg)
        if item not in PROFILE_NAMES:
            msg = (
                f"capability_profiles[{i}]={item!r} is not a known profile; "
                f"must be one of {sorted(PROFILE_NAMES)}"
            )
            raise BuilderError(msg)
        validated.append(item)
    return validated


def _validate_entrypoints(entrypoints: list[Any]) -> list[dict[str, str]]:
    """Validate entrypoint declarations and return them as dicts."""
    validated: list[dict[str, str]] = []
    for i, item in enumerate(entrypoints):
        if not isinstance(item, dict):
            msg = f"entrypoints[{i}] must be an object, got {type(item).__name__}"
            raise BuilderError(msg)
        entrypoint_id = item.get("entrypoint_id")
        if not isinstance(entrypoint_id, str) or entrypoint_id == "":
            msg = f"entrypoints[{i}].entrypoint_id must be a non-empty string"
            raise BuilderError(msg)
        kind = item.get("kind")
        if kind != "python_module":
            msg = f"entrypoints[{i}].kind must be 'python_module', got {kind!r}"
            raise BuilderError(msg)
        ref = item.get("ref")
        if not isinstance(ref, str) or ref == "":
            msg = f"entrypoints[{i}].ref must be a non-empty string"
            raise BuilderError(msg)
        validated.append({"entrypoint_id": entrypoint_id, "kind": kind, "ref": ref})
    return validated


def _license_texts_sha256(workdir: Path, spdx: str) -> list[str]:
    """Compute the license text sha256 from workdir or a deterministic default."""
    candidates = ["LICENSE.txt", "LICENSE"]
    for candidate in candidates:
        path = workdir / candidate
        if path.is_file():
            return [_sha256_bytes(path.read_bytes())]

    template = _DEFAULT_LICENSE_TEMPLATES.get(spdx)
    if template is None:
        # For unknown licenses, fall back to a minimal deterministic text so the
        # manifest can be built, but then the license policy will reject it when
        # the manifest is validated. This keeps the builder focused on bytes.
        template = f"SPDX-License-Identifier: {spdx}\n"
    return [_sha256_bytes(template.encode("utf-8"))]


def _compute_source_sha256(source: dict[str, Any]) -> str:
    """Compute a deterministic source_sha256 from the source metadata."""
    canonical_source = {
        "url": source.get("url"),
        "commit": source.get("commit"),
    }
    return _sha256_canonical(canonical_source)


def _compute_lock_sha256(workdir: Path) -> str:
    """Compute lock_sha256 from ``lock.json`` if present, else the sentinel."""
    lock_path = workdir / "lock.json"
    if lock_path.is_file():
        return _sha256_bytes(lock_path.read_bytes())
    return _EMPTY_SHA256


def _default_probes(entrypoints: list[dict[str, str]]) -> dict[str, str]:
    """Return deterministic probe defaults for the declared entrypoints."""
    if not entrypoints:
        msg = "at least one entrypoint is required to derive default probes"
        raise BuilderError(msg)
    runtime = entrypoints[0]["entrypoint_id"]
    actual = entrypoints[min(1, len(entrypoints) - 1)]["entrypoint_id"]
    return {"runtime_probe": runtime, "actual_compute_probe": actual}


def _validate_license_spdx(spdx: str) -> None:
    """Validate the SPDX identifier against the pack license policy.

    This mirrors the policy in :mod:`srl.packs.manifest` so that the builder
    surfaces license errors as early as possible.
    """
    if spdx in LICENSE_ALLOWLIST:
        return
    if any(spdx.startswith(prefix) for prefix in LICENSE_INCOMPATIBLE_PREFIXES):
        msg = f"license {spdx!r} is incompatible with the SRL pack policy"
        raise LicenseError(msg, fail_reason="LICENSE_INCOMPATIBLE")
    msg = f"license {spdx!r} is not in the SRL pack allowlist"
    raise LicenseError(msg, fail_reason="LICENSE_UNKNOWN")


def build_pack(
    spec: dict[str, Any],
    workdir: str | Path,
) -> tuple[ResourcePackManifest, Path]:
    """Build a validated pack manifest from ``spec`` and the tree in ``workdir``.

    Parameters
    ----------
    spec:
        Declarative pack spec. Required keys: ``name``, ``version``,
        ``capability_profiles``, ``entrypoints``, ``source``, ``license``.
        Optional keys: ``pack_id``, ``platforms``, ``sbom_sha256``, ``probes``,
        ``created_utc``.
    workdir:
        Directory containing the pack files. Must exist. ``tree_sha256`` is
        computed over this tree; ``LICENSE.txt`` / ``lock.json`` are read if
        present.

    Returns
    -------
    tuple[ResourcePackManifest, Path]
        The validated manifest and the absolute tree path.

    Raises
    ------
    BuilderError
        If the spec or tree is malformed.
    LicenseError
        If the declared license is unknown or incompatible.
    """
    workdir_path = Path(workdir)
    if not workdir_path.is_dir():
        msg = f"workdir must be a directory: {workdir_path}"
        raise BuilderError(msg)

    name = _require_str(spec.get("name"), "name")
    version = _require_str(spec.get("version"), "version")
    pack_id = spec.get("pack_id", _derive_pack_id(name, version))
    pack_id = _require_str(pack_id, "pack_id")

    profiles = _require_list(spec.get("capability_profiles"), "capability_profiles")
    validated_profiles = _validate_profiles(profiles)

    entrypoints_raw = _require_list(spec.get("entrypoints"), "entrypoints")
    validated_entrypoints = _validate_entrypoints(entrypoints_raw)

    source_raw = _require_dict(spec.get("source"), "source")
    source_url = _optional_str(source_raw.get("url"), "source.url")
    source_commit = _optional_str(source_raw.get("commit"), "source.commit")
    source_sha256 = _compute_source_sha256({"url": source_url, "commit": source_commit})

    license_raw = _require_dict(spec.get("license"), "license")
    spdx = _require_str(license_raw.get("spdx"), "license.spdx")
    _validate_license_spdx(spdx)
    license_texts_sha256 = _license_texts_sha256(workdir_path, spdx)

    lock_sha256 = _compute_lock_sha256(workdir_path)
    tree_sha256 = compute_tree_sha256(workdir_path)

    platforms = spec.get("platforms", _DEFAULT_PLATFORMS)
    if not isinstance(platforms, list) or not platforms:
        msg = "platforms must be a non-empty list"
        raise BuilderError(msg)

    sbom_sha256 = spec.get("sbom_sha256")
    if sbom_sha256 is not None and not isinstance(sbom_sha256, str):
        msg = f"sbom_sha256 must be a string or null, got {type(sbom_sha256).__name__}"
        raise BuilderError(msg)

    probes = spec.get("probes", _default_probes(validated_entrypoints))
    probes = _require_dict(probes, "probes")
    if not isinstance(probes.get("runtime_probe"), str):
        msg = "probes.runtime_probe must be a string"
        raise BuilderError(msg)
    if not isinstance(probes.get("actual_compute_probe"), str):
        msg = "probes.actual_compute_probe must be a string"
        raise BuilderError(msg)

    created_utc = spec.get("created_utc", _DEFAULT_CREATED_UTC)
    created_utc = _require_str(created_utc, "created_utc")

    manifest_dict: dict[str, Any] = {
        "schema_version": "ResourcePackManifest/v1",
        "pack_id": pack_id,
        "name": name,
        "version": version,
        "capability_profiles": validated_profiles,
        "platforms": platforms,
        "source": {
            "url": source_url,
            "commit": source_commit,
            "source_sha256": source_sha256,
        },
        "lock_sha256": lock_sha256,
        "tree_sha256": tree_sha256,
        "license": {
            "spdx": spdx,
            "texts_sha256": license_texts_sha256,
        },
        "sbom_sha256": sbom_sha256,
        "entrypoints": validated_entrypoints,
        "probes": probes,
        "created_utc": created_utc,
        "canonical_writes": 0,
        "grants_authority": False,
    }

    try:
        manifest = build_manifest(manifest_dict)
    except PackManifestError as exc:
        # Surface builder-side context while preserving the original fail reason.
        msg = f"built manifest failed validation: {exc}"
        raise BuilderError(msg, fail_reason=exc.fail_reason) from exc

    return manifest, workdir_path.resolve()


__all__ = [
    "BuilderError",
    "build_pack",
]
