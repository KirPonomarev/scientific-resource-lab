"""Private overlay resolver for retrospective pilots (WP-G60).

The *private overlay* is how a real operator connects a public, hashes-only
``PilotSpec/v1`` to the operator's private artifact store and private
configuration. A spec carries ``sha256:`` digests of source artifacts but
NEVER the paths to them; this module resolves those digests against the
operator's own private environment.

The load-bearing property: **no private path or identifier ever enters the
public repository.** This module exposes ONLY the generic machinery
(:func:`resolve_overlay` reads two environment variables and returns a typed
:class:`OverlayConfig`). The private configuration file named by
``SRL_PRIVATE_CONFIG`` is NEVER committed, NEVER logged, and NEVER serialized
into a public artifact. The public repo only ever sees the machinery and the
digests.

Why a typed WAIT (never a default guess)
----------------------------------------
If ``SRL_PRIVATE_CONFIG`` or ``SRL_ARTIFACT_STORE`` is absent from the passed
environment, :func:`resolve_overlay` raises :class:`OverlayError` with
``fail_reason`` ``WAIT_ENVIRONMENT`` — an honest wait. It NEVER fabricates a
default path, NEVER falls back to ``~/.srl``, and NEVER guesses a location.
Fabricating a path would (a) hide a misconfigured environment behind a silent
default and (b) risk pointing the analysis at the wrong data. A typed wait is
the honest failure: the environment is not yet ready, retry after setting the
variables.

The wait is non-terminal (``hard_stop=false``, ``retriable=false`` in the
registry): the caller sets the two variables and re-runs.

Environment contract
--------------------
Two environment variables are read, ONLY from the ``env`` dict passed to
:func:`resolve_overlay` (this module never touches ``os.environ`` directly, so
a test can pin the environment deterministically):

- ``SRL_PRIVATE_CONFIG`` — the path to the operator's private overlay config
  file. The file is operator-owned, NEVER committed; this module reads it (so
  it can return a typed config) but the public machinery treats its contents
  as opaque.
- ``SRL_ARTIFACT_STORE`` — the path to the operator's private content-addressed
  artifact store root (where the source-artifact digests are resolved to
  bytes). NEVER committed.

Both variables are REQUIRED. Either missing -> ``WAIT_ENVIRONMENT``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

from srl.contracts.errors import CONTRACT_INVALID_FAIL_REASON, ContractError

# The canonical fail reason for overlay wait: the required private environment
# is not yet available. Mirrors the ``WAIT_ENVIRONMENT`` entry in
# ``automation/fail-reasons.json`` (class ``wait``, ``hard_stop=false``). The
# caller sets the variables and re-runs.
OVERLAY_FAIL_REASON: Final[str] = "WAIT_ENVIRONMENT"

# Structural problems in an otherwise-present overlay (a config file that is
# not valid JSON, a store path that is not a directory) are CONTRACT_INVALID,
# not a wait: the environment was provided but the value is malformed.
OVERLAY_INVALID_FAIL_REASON: Final[str] = CONTRACT_INVALID_FAIL_REASON

#: The environment variable naming the operator's private overlay config file.
#: The file is operator-owned and NEVER committed to the public repo.
PRIVATE_CONFIG_ENV: Final[str] = "SRL_PRIVATE_CONFIG"

#: The environment variable naming the operator's private artifact store root.
#: Used to resolve the source-artifact digests carried by a PilotSpec. NEVER
#: committed to the public repo.
ARTIFACT_STORE_ENV: Final[str] = "SRL_ARTIFACT_STORE"

#: The two environment variables :func:`resolve_overlay` reads. Kept as a
#: tuple so a test can assert the module touches ONLY these (no private path
#: is ever inferred from elsewhere).
REQUIRED_ENV_VARS: Final[tuple[str, ...]] = (PRIVATE_CONFIG_ENV, ARTIFACT_STORE_ENV)


class OverlayError(ContractError):
    """Raised when the private overlay cannot be resolved.

    Two typed shapes:

    - ``fail_reason`` ``WAIT_ENVIRONMENT`` (the default): one or both required
      environment variables are absent. The environment is not yet ready; the
      caller sets them and re-runs. NEVER a fabricated default.
    - ``fail_reason`` ``CONTRACT_INVALID``: an environment variable was
      provided but its value is structurally invalid (the config file is not
      readable / not valid JSON, or the store root is not a directory).

    Attributes
    ----------
    missing_vars:
        The subset of :data:`REQUIRED_ENV_VARS` that were absent, for the
        ``WAIT_ENVIRONMENT`` shape. Empty for the ``CONTRACT_INVALID`` shape.
    """

    def __init__(
        self,
        message: str,
        *,
        missing_vars: tuple[str, ...] = (),
        fail_reason: str = OVERLAY_FAIL_REASON,
    ) -> None:
        super().__init__(message, fail_reason=fail_reason)
        self.missing_vars: Final[tuple[str, ...]] = missing_vars


class OverlayConfig:
    """The resolved private overlay.

    Carries the two resolved, validated paths (the private config file and the
    private artifact store root). It deliberately exposes ONLY the generic
    machinery: no contents of the private config file are surfaced here, so an
    ``OverlayConfig`` instance can be inspected (e.g. in a test or a gate)
    without leaking operator-private contents into a public artifact.

    The class is a thin, frozen value object. The two paths are the resolved
    absolute :class:`pathlib.Path` objects; the private config is NOT read
    into memory by this object (a caller that needs the contents reads the
    file itself, in operator scope).

    Attributes
    ----------
    config_path:
        The absolute path to the operator's private overlay config file
        (resolved from ``SRL_PRIVATE_CONFIG``).
    artifact_store:
        The absolute path to the operator's private content-addressed artifact
        store root (resolved from ``SRL_ARTIFACT_STORE``).
    """

    __slots__ = ("artifact_store", "config_path")

    def __init__(self, config_path: Path, artifact_store: Path) -> None:
        self.config_path: Final[Path] = config_path
        self.artifact_store: Final[Path] = artifact_store

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, OverlayConfig):
            return NotImplemented
        return self.config_path == other.config_path and self.artifact_store == other.artifact_store

    def __hash__(self) -> int:
        return hash((self.config_path, self.artifact_store))

    def __repr__(self) -> str:
        return (
            f"OverlayConfig(config_path={self.config_path!r}, "
            f"artifact_store={self.artifact_store!r})"
        )


def _required_from_env(env: dict[str, str], name: str) -> str | None:
    """Return the stripped value of ``name`` from ``env``, or None if absent.

    A present-but-empty value is treated as absent: an empty path is not a
    usable overlay path, and treating it as absent yields the honest
    ``WAIT_ENVIRONMENT`` rather than a downstream "file not found" that masks
    a misconfiguration.
    """
    raw = env.get(name)
    if not isinstance(raw, str):
        return None
    value = raw.strip()
    return value or None


def resolve_overlay(env: dict[str, str]) -> OverlayConfig:
    """Resolve the private overlay from the passed ``env`` dict.

    Reads ONLY :data:`PRIVATE_CONFIG_ENV` and :data:`ARTIFACT_STORE_ENV` from
    ``env``. This function never touches ``os.environ`` directly, so a caller
    (or a test) fully controls the environment. If either variable is absent
    or empty, the function raises :class:`OverlayError` with
    ``fail_reason`` ``WAIT_ENVIRONMENT`` — an honest wait, NEVER a fabricated
    default path.

    Parameters
    ----------
    env:
        The environment mapping to read. Must be a dict (or mapping) the
        caller fully controls. Production callers pass ``os.environ``; tests
        pass a pinned dict.

    Returns
    -------
    OverlayConfig
        The resolved overlay, carrying the two validated absolute paths.

    Raises
    ------
    OverlayError
        With ``fail_reason`` ``WAIT_ENVIRONMENT`` if one or both required
        variables are absent/empty (the missing names are in
        ``exc.missing_vars``); or with ``fail_reason`` ``CONTRACT_INVALID``
        if a variable was provided but its value is structurally invalid (the
        config file is unreadable / not valid JSON, or the store root is not
        an existing directory).

    Notes
    -----
    The function resolves the two paths to absolute form and validates their
    existence:

    - ``SRL_ARTIFACT_STORE`` MUST name an existing directory (it is the root
      the content-addressed store mounts at; a non-directory or a missing path
      is a structural misconfiguration, not a wait).
    - ``SRL_PRIVATE_CONFIG`` MUST name a readable file whose contents parse as
      JSON (the private overlay config is a JSON object). The parsed contents
      are NOT returned by this function — a caller reads them in operator
      scope — but the structural check happens here so a downstream consumer
      never receives a half-resolved overlay pointing at a malformed file.

    The config file's contents are never serialized into any public artifact;
    this function is the entire surface, and it returns only the two paths.
    """
    # Collect the missing variables so the wait reason is precise. A present-
    # but-empty value is treated as missing (see _required_from_env).
    missing: list[str] = []
    config_value = _required_from_env(env, PRIVATE_CONFIG_ENV)
    if config_value is None:
        missing.append(PRIVATE_CONFIG_ENV)
    store_value = _required_from_env(env, ARTIFACT_STORE_ENV)
    if store_value is None:
        missing.append(ARTIFACT_STORE_ENV)
    if missing:
        joined = ", ".join(missing)
        msg = (
            f"private overlay environment is not ready: missing required "
            f"variable(s) {joined}; set them and re-run (an overlay is never "
            f"resolved from a fabricated default path)"
        )
        raise OverlayError(msg, missing_vars=tuple(missing))

    # Both variables are present and non-empty. Resolve to absolute paths and
    # validate structure. Structural failures are CONTRACT_INVALID (the
    # environment was provided but the value is malformed), not a wait.
    assert config_value is not None  # noqa: S101 (narrow for mypy; checked above)
    assert store_value is not None  # noqa: S101 (narrow for mypy; checked above)
    config_path = Path(config_value).expanduser().resolve()
    store_path = Path(store_value).expanduser().resolve()

    # The artifact store MUST be an existing directory. A missing path or a
    # non-directory is a structural misconfiguration.
    if not store_path.is_dir():
        msg = (
            f"artifact store root {store_value!r} resolved to "
            f"{str(store_path)!r} which is not an existing directory"
        )
        raise OverlayError(msg, fail_reason=OVERLAY_INVALID_FAIL_REASON)

    # The private config file MUST be a readable file whose contents parse as
    # JSON. The parsed contents are discarded: this function returns only the
    # two paths, so no private content crosses into the returned object. The
    # parse is a structural validation that the file is usable.
    if not config_path.is_file():
        msg = (
            f"private config {config_value!r} resolved to {str(config_path)!r} "
            f"which is not an existing file"
        )
        raise OverlayError(msg, fail_reason=OVERLAY_INVALID_FAIL_REASON)
    try:
        raw = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"private config {str(config_path)!r} could not be read: {exc}"
        raise OverlayError(msg, fail_reason=OVERLAY_INVALID_FAIL_REASON) from exc
    # The contents are parsed only to validate they are a JSON object; the
    # parsed value is intentionally not returned. See module docstring.
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"private config {str(config_path)!r} is not valid JSON: {exc}"
        raise OverlayError(msg, fail_reason=OVERLAY_INVALID_FAIL_REASON) from exc
    if not isinstance(parsed, dict):
        msg = (
            f"private config {str(config_path)!r} must be a JSON object, "
            f"got {type(parsed).__name__}"
        )
        raise OverlayError(msg, fail_reason=OVERLAY_INVALID_FAIL_REASON)

    return OverlayConfig(config_path=config_path, artifact_store=store_path)


__all__ = [
    "ARTIFACT_STORE_ENV",
    "OVERLAY_FAIL_REASON",
    "OVERLAY_INVALID_FAIL_REASON",
    "PRIVATE_CONFIG_ENV",
    "REQUIRED_ENV_VARS",
    "OverlayConfig",
    "OverlayError",
    "resolve_overlay",
]
