"""Static site generator for the SRL evidence portal (WP-F52).

This module is intentionally **stdlib-only**: it may not import third-party
packages, and the HTML it emits must contain no external resource references
and no JavaScript. All pages are generated from :class:`string.Template`
templates under ``portal/templates/`` and hand-rolled HTML escaping.
"""

from __future__ import annotations

import datetime
import enum
import hashlib
import importlib.metadata
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Any, Final

# ---------------------------------------------------------------------------
# Public API types
# ---------------------------------------------------------------------------


class PortalMode(enum.Enum):
    """Build mode for the static portal."""

    private_local = "private_local"
    public_demo = "public_demo"


@dataclass
class PortalBuildReport:
    """Receipt returned by :func:`build_portal`."""

    mode: PortalMode
    output_dir: Path
    success: bool
    objects_scanned: int
    objects_accepted: int
    objects_refused: int
    leak_detected: bool
    refusals: list[dict[str, Any]] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)
    generator_version: str = ""
    built_at: str = ""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_GENERATOR_NAME: Final[str] = "srl-portal"
_PUBLIC_DEMO_MARKER: Final[str] = "DEMO — synthetic public data only"
_TEMPLATE_DIR: Final[Path] = Path(__file__).resolve().parents[3] / "portal" / "templates"

# Regexps for public-demo leak detection. These are intentionally broad:
# any string that looks like an absolute local filesystem path or that carries
# a credential-like keyword is a public-demo leak.
_ABSOLUTE_UNIX_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:^|/)(?:Users|home|root|etc|var|tmp|private|opt)/[^/\s]+"
)
_WINDOWS_DRIVE_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z]:[/\\]")
_CREDENTIAL_RE: Final[re.Pattern[str]] = re.compile(
    r"(?i)\b(?:password|secret|token|api_key|private_key|credential|"
    r"credentials|bearer|aws_access_key_id|aws_secret_access_key|"
    r"ssh-rsa|-----BEGIN|AKIA[0-9A-Z]{16})\b"
)

# 11 evidence axes, in canonical order (mirrors srl.semantic.evidence).
_AXIS_NAMES: Final[tuple[str, ...]] = (
    "capability_state",
    "exercise_level",
    "engine_execution",
    "scientific_check",
    "formal_check",
    "formal_scope",
    "statistical_support",
    "causal_identification",
    "algorithmic_cross_engine_reproduction",
    "independent_empirical_replication",
    "integration_authority",
)


# ---------------------------------------------------------------------------
# HTML escaping (hand-rolled, no html.escape dependency)
# ---------------------------------------------------------------------------


def escape_html(value: object) -> str:
    """Escape a value for safe insertion into HTML text or attributes."""
    text = str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


# ---------------------------------------------------------------------------
# Object loading and identity
# ---------------------------------------------------------------------------


def _object_identifier(obj: dict[str, Any]) -> str:
    """Return a stable identifier for an object.

    If the object is already an ``ScientificObjectEnvelope/v1`` with an
    ``object_id``, that id is used. Otherwise a local content-hash id is
    computed so the portal can still cross-link objects.
    """
    candidate = obj.get("object_id")
    if isinstance(candidate, str):
        return candidate
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"local:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def _load_objects(objects_dir: Path) -> list[tuple[str, dict[str, Any]]]:
    """Load every ``*.json`` file in ``objects_dir`` as one or more objects."""
    objects: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(objects_dir.iterdir()):
        if not path.is_file() or path.suffix != ".json":
            continue
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            objects.append((_object_identifier(obj), obj))
    return objects


# ---------------------------------------------------------------------------
# Public-demo boundary enforcement
# ---------------------------------------------------------------------------


def _detect_leak(value: Any, leaks: list[str]) -> None:
    """Recursively scan ``value`` for absolute local paths / credential patterns."""
    if isinstance(value, dict):
        for key, val in value.items():
            if isinstance(key, str):
                _scan_string(key, leaks)
            _detect_leak(val, leaks)
    elif isinstance(value, list):
        for item in value:
            _detect_leak(item, leaks)
    elif isinstance(value, str):
        _scan_string(value, leaks)


def _scan_string(text: str, leaks: list[str]) -> None:
    """Check a single string for leak patterns."""
    if _ABSOLUTE_UNIX_RE.search(text) or _WINDOWS_DRIVE_RE.search(text):
        leaks.append(f"absolute local path: {text[:120]!r}")
    if _CREDENTIAL_RE.search(text):
        leaks.append(f"credential pattern: {text[:120]!r}")


def _contains_public_marker(value: Any) -> bool:
    """Return ``True`` if any string in ``value`` references ``fixtures/public/``."""
    if isinstance(value, dict):
        return any(_contains_public_marker(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_public_marker(item) for item in value)
    if isinstance(value, str):
        return "fixtures/public/" in value
    return False


def _is_public_synthetic(obj: dict[str, Any]) -> bool:
    """Return ``True`` if ``obj`` can be proven to derive from the public corpus."""
    if obj.get("synthetic") is True:
        return True
    if obj.get("license") == "CC0-1.0":
        return True
    return _contains_public_marker(obj)


# ---------------------------------------------------------------------------
# Templating
# ---------------------------------------------------------------------------


def _load_template(name: str) -> Template:
    """Load a ``string.Template`` from ``portal/templates/``."""
    path = _TEMPLATE_DIR / name
    return Template(path.read_text(encoding="utf-8"))


def _render_page(
    *,
    title: str,
    content: str,
    mode: PortalMode,
    generator_version: str,
    built_at: str,
) -> str:
    """Wrap ``content`` in the base template and return a full HTML page."""
    base = _load_template("base.html")
    watermark = ""
    if mode is PortalMode.public_demo:
        banner = escape_html(_PUBLIC_DEMO_MARKER)
        watermark = f'<div class="watermark">{banner}</div>'
    return base.substitute(
        title=escape_html(title),
        watermark=watermark,
        content=content,
        generator=escape_html(f"{_GENERATOR_NAME}/{generator_version}"),
        built_at=escape_html(built_at),
    )


# ---------------------------------------------------------------------------
# Page renderers
# ---------------------------------------------------------------------------


def _safe_filename(obj_id: str) -> str:
    """Return a filesystem-safe fragment for an object id."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", obj_id)


def _object_type(obj: dict[str, Any]) -> str:
    """Best-effort object type label."""
    object_type = obj.get("object_type")
    if isinstance(object_type, str):
        return object_type
    schema_version = obj.get("schema_version")
    if isinstance(schema_version, str):
        return schema_version.split("/")[0].lower()
    return type(obj).__name__


def _object_created(obj: dict[str, Any]) -> str:
    """Best-effort created timestamp."""
    return str(obj.get("created_utc", "unknown"))


def _render_index(
    accepted: list[tuple[str, dict[str, Any]]],
    mode: PortalMode,
    generator_version: str,
    built_at: str,
) -> tuple[str, str]:
    """Render the portal index page."""
    template = _load_template("index.html")
    rows: list[str] = []
    for obj_id, obj in accepted:
        safe_id = _safe_filename(obj_id)
        rows.append(
            "<tr>"
            f'<td><a href="obj_{safe_id}.html">{escape_html(obj_id)}</a></td>'
            f"<td>{escape_html(_object_type(obj))}</td>"
            f"<td>{escape_html(_object_created(obj))}</td>"
            "</tr>"
        )
    content = template.substitute(
        mode=escape_html(mode.value),
        object_count=str(len(accepted)),
        object_rows="\n".join(rows) if rows else '<tr><td colspan="3">No objects</td></tr>',
    )
    return "index.html", _render_page(
        title="SRL Portal — Capability Catalog",
        content=content,
        mode=mode,
        generator_version=generator_version,
        built_at=built_at,
    )


def _render_object_detail(  # noqa: PLR0913,PLR0917
    obj_id: str,
    obj: dict[str, Any],
    object_map: dict[str, dict[str, Any]],
    mode: PortalMode,
    generator_version: str,
    built_at: str,
) -> tuple[str, str]:
    """Render a single object detail page."""
    template = _load_template("object.html")
    parents = obj.get("parents", [])
    if isinstance(parents, list) and parents:
        parent_links: list[str] = []
        for parent_id in parents:
            if isinstance(parent_id, str) and parent_id in object_map:
                safe = _safe_filename(parent_id)
                parent_links.append(f'<a href="obj_{safe}.html">{escape_html(parent_id)}</a>')
            else:
                parent_links.append(escape_html(str(parent_id)))
        parents_html = "<ul><li>" + "</li><li>".join(parent_links) + "</li></ul>"
    else:
        parents_html = "<p>None</p>"

    payload = obj.get("payload", obj)
    payload_json = json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)
    content = template.substitute(
        object_id=escape_html(obj_id),
        object_type=escape_html(_object_type(obj)),
        created=escape_html(_object_created(obj)),
        parents=parents_html,
        payload=escape_html(payload_json),
    )
    filename = f"obj_{_safe_filename(obj_id)}.html"
    return filename, _render_page(
        title=f"Object {obj_id}",
        content=content,
        mode=mode,
        generator_version=generator_version,
        built_at=built_at,
    )


def _render_lineage(
    accepted: list[tuple[str, dict[str, Any]]],
    object_map: dict[str, dict[str, Any]],
    mode: PortalMode,
    generator_version: str,
    built_at: str,
) -> tuple[str, str]:
    """Render the transformation lineage page."""
    template = _load_template("lineage.html")
    sections: list[str] = []
    for obj_id, obj in accepted:
        parents = obj.get("parents", [])
        if isinstance(parents, list) and parents:
            items: list[str] = []
            for parent_id in parents:
                if isinstance(parent_id, str) and parent_id in object_map:
                    safe = _safe_filename(parent_id)
                    loss = escape_html(_lossiness_note(obj, object_map.get(parent_id)))
                    items.append(
                        "<li>"
                        f'Parent: <a href="obj_{safe}.html">{escape_html(parent_id)}</a>'
                        f" — lossiness: <em>{loss}</em>"
                        "</li>"
                    )
                else:
                    items.append(
                        f"<li>Parent: {escape_html(str(parent_id))} "
                        f"(lossiness: <em>parent not in corpus</em>)</li>"
                    )
            sections.append(f"<h2>{escape_html(obj_id)}</h2><ul>{''.join(items)}</ul>")
        else:
            sections.append(f"<h2>{escape_html(obj_id)}</h2><p>Root object (no parents).</p>")
    rows = "\n".join(sections) if sections else "<p>No lineage data.</p>"
    content = template.substitute(lineage_rows=rows)
    return "lineage.html", _render_page(
        title="Transformation Lineage",
        content=content,
        mode=mode,
        generator_version=generator_version,
        built_at=built_at,
    )


def _lossiness_note(child: dict[str, Any], parent: dict[str, Any] | None) -> str:
    """Return a short lossiness description for a child/parent pair."""
    child_type = _object_type(child)
    parent_type = _object_type(parent) if parent else "unknown"
    if child_type == parent_type:
        return "same type; verify fidelity"
    if child_type in {"transformation_receipt", "run_receipt"}:
        return "transformation metadata may drop intermediate state"
    return f"{parent_type} -> {child_type}"


def _extract_axes(obj: dict[str, Any]) -> dict[str, str] | None:
    """Return the 11-axis evidence object if present."""
    if isinstance(obj.get("axes"), dict):
        return {name: str(obj["axes"].get(name, "n/a")) for name in _AXIS_NAMES}
    payload = obj.get("payload", {})
    if isinstance(payload, dict) and isinstance(payload.get("axes"), dict):
        return {name: str(payload["axes"].get(name, "n/a")) for name in _AXIS_NAMES}
    return None


def _render_evidence(
    accepted: list[tuple[str, dict[str, Any]]],
    mode: PortalMode,
    generator_version: str,
    built_at: str,
) -> tuple[str, str]:
    """Render the evidence matrix page."""
    template = _load_template("evidence.html")
    sections: list[str] = []
    for obj_id, obj in accepted:
        axes = _extract_axes(obj)
        if axes is None:
            continue
        rows = "\n".join(
            f"<tr><td>{escape_html(name)}</td><td>{escape_html(value)}</td></tr>"
            for name, value in axes.items()
        )
        safe = _safe_filename(obj_id)
        sections.append(
            f'<h2 id="{safe}">{escape_html(obj_id)}</h2>'
            f"<table><thead><tr><th>Axis</th><th>Value</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
    content = template.substitute(
        evidence_tables="\n".join(sections) if sections else "<p>No evidence assessments.</p>"
    )
    return "evidence.html", _render_page(
        title="Evidence Matrix",
        content=content,
        mode=mode,
        generator_version=generator_version,
        built_at=built_at,
    )


def _extract_resources(obj: dict[str, Any]) -> dict[str, Any] | None:
    """Return resource-usage data if present."""
    resources = obj.get("resource_usage")
    if isinstance(resources, dict):
        return dict(resources)
    payload = obj.get("payload", {})
    if isinstance(payload, dict):
        payload_resources = payload.get("resource_usage")
        if isinstance(payload_resources, dict):
            return dict(payload_resources)
    # Engine receipts carry wall_seconds / rss_bytes directly.
    if isinstance(obj.get("wall_seconds"), int) and isinstance(obj.get("rss_bytes"), int):
        return {"wall_seconds": obj["wall_seconds"], "rss_bytes": obj["rss_bytes"]}
    return None


def _render_resources(
    accepted: list[tuple[str, dict[str, Any]]],
    mode: PortalMode,
    generator_version: str,
    built_at: str,
) -> tuple[str, str]:
    """Render the run resources page."""
    template = _load_template("resources.html")
    sections: list[str] = []
    for obj_id, obj in accepted:
        usage = _extract_resources(obj)
        if usage is None:
            continue
        rows = "\n".join(
            f"<tr><td>{escape_html(key)}</td><td>{escape_html(value)}</td></tr>"
            for key, value in usage.items()
        )
        safe = _safe_filename(obj_id)
        sections.append(
            f'<h2 id="{safe}">{escape_html(obj_id)}</h2>'
            f"<table><thead><tr><th>Metric</th><th>Value</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
    content = template.substitute(
        resource_tables="\n".join(sections) if sections else "<p>No run resource data.</p>"
    )
    return "resources.html", _render_page(
        title="Run Resources",
        content=content,
        mode=mode,
        generator_version=generator_version,
        built_at=built_at,
    )


def _extract_interfaces(obj: dict[str, Any]) -> dict[str, Any] | None:
    """Return model-interface data if present."""
    payload = obj.get("payload")
    if obj.get("object_type") == "model_interface" and isinstance(payload, dict):
        return dict(payload)
    if isinstance(payload, dict):
        schema_version = str(payload.get("schema_version", "")).lower()
        if "model_interface" in schema_version:
            return dict(payload)
    return None


def _render_interfaces(
    accepted: list[tuple[str, dict[str, Any]]],
    mode: PortalMode,
    generator_version: str,
    built_at: str,
) -> tuple[str, str]:
    """Render the model interfaces page (integration authority is always none)."""
    template = _load_template("interfaces.html")
    sections: list[str] = []
    for obj_id, obj in accepted:
        iface = _extract_interfaces(obj)
        if iface is None:
            continue
        rows = "\n".join(
            f"<tr><td>{escape_html(key)}</td><td>{escape_html(value)}</td></tr>"
            for key, value in iface.items()
        )
        safe = _safe_filename(obj_id)
        sections.append(
            f'<h2 id="{safe}">{escape_html(obj_id)}</h2>'
            f"<table><thead><tr><th>Field</th><th>Value</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>"
        )
    content = template.substitute(
        interface_tables="\n".join(sections) if sections else "<p>No model interfaces.</p>"
    )
    return "interfaces.html", _render_page(
        title="Model Interfaces",
        content=content,
        mode=mode,
        generator_version=generator_version,
        built_at=built_at,
    )


# ---------------------------------------------------------------------------
# Site assembly
# ---------------------------------------------------------------------------


def _generator_version() -> str:
    """Return the portal generator version."""
    try:
        return importlib.metadata.version("srlab")
    except Exception:  # pragma: no cover - package may not be installed
        return "0.2.0-dev"


def _render_site(  # noqa: PLR0913,PLR0917
    object_map: dict[str, dict[str, Any]],
    accepted: list[tuple[str, dict[str, Any]]],
    out_dir: Path,
    mode: PortalMode,
    generator_version: str,
    built_at: str,
) -> list[str]:
    """Write all static pages and return the list of generated filenames."""
    pages: list[str] = []

    def write(filename: str, html: str) -> None:
        (out_dir / filename).write_text(html, encoding="utf-8")
        pages.append(filename)

    name, html = _render_index(accepted, mode, generator_version, built_at)
    write(name, html)

    for obj_id, obj in accepted:
        name, html = _render_object_detail(
            obj_id, obj, object_map, mode, generator_version, built_at
        )
        write(name, html)

    name, html = _render_lineage(accepted, object_map, mode, generator_version, built_at)
    write(name, html)

    name, html = _render_evidence(accepted, mode, generator_version, built_at)
    write(name, html)

    name, html = _render_resources(accepted, mode, generator_version, built_at)
    write(name, html)

    name, html = _render_interfaces(accepted, mode, generator_version, built_at)
    write(name, html)

    return sorted(pages)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_portal(
    objects_dir: str | Path,
    out_dir: str | Path,
    mode: PortalMode,
) -> PortalBuildReport:
    """Generate a static evidence portal from a directory of JSON objects.

    Parameters
    ----------
    objects_dir:
        Directory containing ``*.json`` object files (one JSON value per line).
    out_dir:
        Directory to write the generated static site into.
    mode:
        ``PortalMode.private_local`` keeps all objects and does not watermark.
        ``PortalMode.public_demo`` drops non-synthetic objects and refuses any
        input that contains absolute local paths or credential patterns with a
        typed ``PUBLIC_LEAK_DETECTED`` refusal.

    Returns
    -------
    PortalBuildReport
        A receipt describing what was scanned, accepted, refused, and generated.
    """
    if not isinstance(mode, PortalMode):
        msg = f"mode must be a PortalMode, got {type(mode).__name__}"  # type: ignore[unreachable]
        raise TypeError(msg)

    objects_dir = Path(objects_dir)
    out_dir = Path(out_dir)

    if not objects_dir.is_dir():
        msg = f"objects_dir is not a directory: {objects_dir}"
        raise ValueError(msg)

    out_dir.mkdir(parents=True, exist_ok=True)

    built_at = datetime.datetime.now(datetime.UTC).isoformat()
    generator_version = _generator_version()

    raw_objects = _load_objects(objects_dir)
    object_map: dict[str, dict[str, Any]] = {}
    accepted: list[tuple[str, dict[str, Any]]] = []
    refusals: list[dict[str, Any]] = []
    leak_detected = False

    for obj_id, obj in raw_objects:
        if mode is PortalMode.public_demo:
            leaks: list[str] = []
            _detect_leak(obj, leaks)
            if leaks:
                leak_detected = True
                refusals.append(
                    {
                        "object_id": obj_id,
                        "reason": "PUBLIC_LEAK_DETECTED",
                        "details": leaks,
                    }
                )
                continue

        if mode is PortalMode.public_demo and not _is_public_synthetic(obj):
            refusals.append(
                {
                    "object_id": obj_id,
                    "reason": "PUBLIC_NON_SYNTHETIC",
                }
            )
            continue

        accepted.append((obj_id, obj))
        object_map[obj_id] = obj

    # A public-demo build fails closed when any leak is detected.
    success = not (mode is PortalMode.public_demo and leak_detected)
    pages: list[str] = []
    if success:
        pages = _render_site(object_map, accepted, out_dir, mode, generator_version, built_at)

    return PortalBuildReport(
        mode=mode,
        output_dir=out_dir,
        success=success,
        objects_scanned=len(raw_objects),
        objects_accepted=len(accepted),
        objects_refused=len(refusals),
        leak_detected=leak_detected,
        refusals=refusals,
        pages=pages,
        generator_version=generator_version,
        built_at=built_at,
    )


__all__ = [
    "PortalBuildReport",
    "PortalMode",
    "build_portal",
    "escape_html",
]
