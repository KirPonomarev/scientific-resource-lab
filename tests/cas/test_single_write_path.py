"""Architecture regression: the CAS engine is the single write path into objects/.

The receipt-last invariant (see ``docs/architecture/cas-engine.md``) only holds
if there is exactly **one** place that publishes bytes into the ``objects/``
tree: the transaction engine (``srl.cas.engine``). If a second write path ever
re-appears (e.g. a "fast" ``LocalArtifactStore.put`` that renames straight into
``objects/<shard>/<digest>``), it would bypass the descriptor + receipt and
break the invariant the engine enforces — exactly the defect the red-team
review flagged on cycle 1.

These tests enforce the invariant **structurally** (not just behaviorally) by
scanning the CAS source tree:

1. ``test_only_engine_module_publishes_into_objects`` — every ``os.replace``
   (or ``os.rename``) call whose destination resolves into the ``objects/``
   tree lives in ``srl/cas/engine.py`` and nowhere else under ``src/``. The
   store module (``srl/cas/store.py``) is explicitly *not* permitted to publish
   directly; its ``put`` must delegate to the engine.
2. ``test_store_put_delegates_to_engine`` — behavioral confirmation that
   :meth:`LocalArtifactStore.put` publishes a descriptor and a receipt (i.e.
   it went through the transaction), so there is no descriptor-less bypass.

The source scan is AST-based so it cannot be defeated by formatting tricks
(one-line ``if`` bodies, walrus expressions, etc.): it walks every call node
and checks whether the destination argument is a path that could land in
``objects/``. The allow-list is intentionally a single module (``engine``); a
new publisher must be added there, not smuggled into another module.
"""

from __future__ import annotations

import ast
from pathlib import Path

from srl.cas import LocalArtifactStore

# The repository root, derived from this test file's location.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _REPO_ROOT / "src"

# The only module permitted to publish into the objects/ tree. A new publisher
# must be added here (and is almost always a mistake).
_OBJECTS_PUBLISHER_ALLOWLIST: frozenset[str] = frozenset({"srl/cas/engine.py"})

# The os calls that atomically (or semi-atomically) move a file into place, and
# so are the operations that could publish into objects/.
_PUBLISH_CALLS: frozenset[str] = frozenset({"replace", "rename"})


def _module_relpath(path: Path) -> str:
    """Return the path of ``path`` relative to ``src/`` (e.g. ``srl/cas/engine.py``)."""
    return path.relative_to(_SRC_ROOT).as_posix()


def _str_arg_into_objects(arg: ast.expr) -> bool:
    """Return True iff ``arg`` (the destination of an os.replace/rename) could land in objects/.

    The destination is "objects-bound" if it is a path whose tail component is a
    child of an ``objects`` directory, OR is built from an ``objects`` attribute
    / subscript / call on a store-paths object. We match conservatively: any
    reference to the literal ``"objects"`` segment, an ``objects`` attribute, or
    an ``object`` attribute (the engine's ``paths.object`` publish target)
    counts as objects-bound so a new publish site is never silently missed.
    """
    # Path("...", "objects", ...) or ".../objects/..." string literal.
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return "objects" in arg.value.replace("\\", "/").split("/")
    # An f-string whose parts mention "objects".
    if isinstance(arg, ast.JoinedStr):
        return any(
            isinstance(p, ast.Constant)
            and isinstance(p.value, str)
            and "objects" in p.value.replace("\\", "/").split("/")
            for p in arg.values
        )
    # paths.object / paths.objects — attribute on a store-paths object.
    if isinstance(arg, ast.Attribute):
        return arg.attr in {"object", "objects"}
    # something["objects"] / something[shard] — conservative: any subscripted
    # destination could be objects-bound.
    if isinstance(arg, ast.Subscript):
        return True
    # A call that builds an objects path (e.g. self._object_path(digest)).
    if isinstance(arg, ast.Call):
        return isinstance(arg.func, ast.Attribute) and arg.func.attr.startswith("_object")
    return False


def _find_publish_calls(tree: ast.AST, src: str) -> list[tuple[int, str, ast.expr]]:
    """Yield (lineno, call_name, dst_arg) for every os.replace/os.rename in ``tree``.

    Matches both ``os.replace(...)`` and a bare ``replace(...)`` (in case the
    module did ``from os import replace``). The destination is the second
    positional argument.
    """
    out: list[tuple[int, str, ast.expr]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = ""
        if isinstance(func, ast.Attribute) and func.attr in _PUBLISH_CALLS:
            # os.replace / os.rename, or module qualified.
            if isinstance(func.value, ast.Name) and func.value.id in {"os", "posix"}:
                name = func.attr
            elif isinstance(func.value, ast.Name):
                # A local alias bound to os (e.g. _os = os; _os.replace).
                name = func.attr
        elif isinstance(func, ast.Name) and func.id in _PUBLISH_CALLS:
            name = func.id
        if not name:
            continue
        # The destination is the 2nd positional argument (src, dst).
        if len(node.args) < 2:
            continue
        dst = node.args[1]
        out.append((node.lineno, name, dst))
    return out


def test_only_engine_module_publishes_into_objects() -> None:
    """No module outside ``srl/cas/engine.py`` does an os.replace/rename into objects/."""
    violations: list[str] = []
    for py in sorted(_SRC_ROOT.rglob("*.py")):
        rel = _module_relpath(py)
        src = py.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src, filename=str(py))
        except SyntaxError:  # pragma: no cover (a source file must parse)
            continue
        for lineno, name, dst in _find_publish_calls(tree, src):
            if not _str_arg_into_objects(dst):
                continue
            if rel in _OBJECTS_PUBLISHER_ALLOWLIST:
                continue
            violations.append(
                f"{rel}:{lineno}: os.{name}(...) publishes into objects/ (engine-only)"
            )

    assert not violations, (
        "the CAS engine (srl/cas/engine.py) is the only module permitted to publish "
        "into the objects/ tree; found objects-bound os.replace/rename calls outside it:\n  "
        + "\n  ".join(violations)
    )


def test_store_module_has_no_direct_objects_publish() -> None:
    """The store module performs no os.replace/rename at all (it delegates to the engine)."""
    store_src = (_SRC_ROOT / "srl" / "cas" / "store.py").read_text(encoding="utf-8")
    tree = ast.parse(store_src, filename="store.py")
    direct: list[str] = []
    for lineno, name, _dst in _find_publish_calls(tree, store_src):
        direct.append(f"store.py:{lineno}: os.{name}(...) — store must not publish directly")
    assert not direct, (
        "srl/cas/store.py must delegate every write to the engine; found a direct "
        "os.replace/os.rename:\n  " + "\n  ".join(direct)
    )


def test_store_put_delegates_to_engine(tmp_path: Path) -> None:
    """Behavioral: LocalArtifactStore.put publishes a descriptor + receipt (engine path)."""
    store = LocalArtifactStore(tmp_path)
    desc = store.put(b"single-write-path-probe")
    # The engine path writes a descriptor and a receipt alongside the object.
    desc_files = list((tmp_path / "descriptors").glob("*.json"))
    receipt_files = list((tmp_path / "receipts").glob("*.json"))
    assert len(desc_files) == 1, "put() did not write a descriptor (engine bypass?)"
    assert len(receipt_files) == 1, "put() did not write a receipt (engine bypass?)"
    assert store.get(desc.digest) == b"single-write-path-probe"
