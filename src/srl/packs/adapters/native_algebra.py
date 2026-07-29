"""V3.7 A08 native algebra and native SMT executable probes.

The A08 packs are external native executables, not Python packages and not
vendored SRL dependencies. This module keeps them behind a bounded subprocess
surface: no shell, fixed command vectors, fixed stdin payloads, short timeouts,
and tiny smoke problems with independent crosschecks.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

A08_NATIVE_SCHEMA_VERSION: Final[str] = "A08NativeAlgebraSmoke/v1"
_TIMEOUT_SECONDS: Final[float] = 20.0


class A08ToolState(StrEnum):
    """Truth state for one A08 native executable."""

    ACTIVE = "ACTIVE"
    WAIT_TOOLCHAIN = "WAIT_TOOLCHAIN"


@dataclass(frozen=True, slots=True)
class A08ToolProbe:
    """Executable probe + scientific smoke for one native A08 tool."""

    component_id: str
    executable: str | None
    state: A08ToolState
    version_detail: str | None
    license_spdx: str
    license_boundary: str
    smoke_detail: str
    crosscheck_detail: str
    error: str | None = None

    @property
    def active(self) -> bool:
        """Whether the tool reached ACTIVE."""
        return self.state is A08ToolState.ACTIVE

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        data = asdict(self)
        data["state"] = str(self.state)
        data["active"] = self.active
        return data


@dataclass(frozen=True, slots=True)
class A08NativeSmoke:
    """Bundle of A08 native algebra and SMT smoke results."""

    schema_version: str
    tools: tuple[A08ToolProbe, ...]

    @property
    def active_component_ids(self) -> tuple[str, ...]:
        """A08 component ids that reached ACTIVE."""
        return tuple(item.component_id for item in self.tools if item.active)

    @property
    def wait_component_ids(self) -> tuple[str, ...]:
        """A08 component ids still waiting on toolchain closure."""
        return tuple(item.component_id for item in self.tools if not item.active)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation."""
        return {
            "schema_version": self.schema_version,
            "active_component_ids": list(self.active_component_ids),
            "wait_component_ids": list(self.wait_component_ids),
            "tools": [item.to_dict() for item in self.tools],
        }


def run_a08_native_smoke() -> A08NativeSmoke:
    """Run all A08 executable probes and bounded scientific smokes."""
    return A08NativeSmoke(
        schema_version=A08_NATIVE_SCHEMA_VERSION,
        tools=(
            _probe_pari_gp(),
            _probe_maxima(),
            _probe_gap(),
            _probe_singular(),
            _probe_z3_native(),
            _probe_cvc5_native(),
        ),
    )


def _base_env() -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", ""),
        "LC_ALL": "C",
        "TERM": "dumb",
    }


def _is_project_virtualenv_path(path: str) -> bool:
    parts = Path(path).parts
    return ".venv" in parts


def _which(candidates: tuple[str, ...]) -> str | None:
    search_path = os.environ.get("PATH", "")
    for candidate in candidates:
        for directory in search_path.split(os.pathsep):
            if not directory or _is_project_virtualenv_path(directory):
                continue
            resolved = shutil.which(candidate, path=directory)
            if resolved and not _is_project_virtualenv_path(resolved):
                return resolved
    return None


def _run(
    command: tuple[str, ...],
    *,
    stdin: str = "",
    timeout_seconds: float = _TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - command vectors are fixed inside this adapter.
        command,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
        env=_base_env(),
    )


def _first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def _version(executable: str, args: tuple[str, ...]) -> str:
    proc = _run((executable, *args), timeout_seconds=10.0)
    return _first_line(proc.stdout or proc.stderr)


def _gap_version(executable: str) -> str:
    version = _version(executable, ("--version",))
    if version:
        return version
    proc = _run(
        (executable, "-q"),
        stdin='Print(GAPInfo.Version, "\\n"); QUIT;\n',
        timeout_seconds=10.0,
    )
    return _first_line(proc.stdout or proc.stderr)


def _wait(component_id: str, error: str, license_spdx: str) -> A08ToolProbe:
    return A08ToolProbe(
        component_id=component_id,
        executable=None,
        state=A08ToolState.WAIT_TOOLCHAIN,
        version_detail=None,
        license_spdx=license_spdx,
        license_boundary="external native executable; not vendored and not in uv.lock",
        smoke_detail="not run",
        crosscheck_detail="missing executable prevents nonfixture smoke",
        error=error,
    )


def _active(  # noqa: PLR0913, PLR0917 - mirrors the A08 evidence axes.
    component_id: str,
    executable: str,
    version_detail: str,
    license_spdx: str,
    smoke_detail: str,
    crosscheck_detail: str,
) -> A08ToolProbe:
    return A08ToolProbe(
        component_id=component_id,
        executable=executable,
        state=A08ToolState.ACTIVE,
        version_detail=version_detail,
        license_spdx=license_spdx,
        license_boundary="external native executable; not vendored and not in uv.lock",
        smoke_detail=smoke_detail,
        crosscheck_detail=crosscheck_detail,
    )


def _probe_pari_gp() -> A08ToolProbe:
    exe = _which(("gp",))
    if exe is None:
        return _wait("pari-gp", "gp executable not found on PATH", "GPL-2.0-or-later")
    proc = _run(
        (exe, "-q", "-f"),
        stdin="print(83*97)\nprint(znorder(Mod(3,7)))\n\\q\n",
    )
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if proc.returncode != 0 or lines != ["8051", "6"]:
        return _wait(
            "pari-gp",
            f"PARI/GP smoke failed: {proc.stderr or proc.stdout}",
            "GPL-2.0-or-later",
        )
    return _active(
        "pari-gp",
        exe,
        _version(exe, ("--version",)),
        "GPL-2.0-or-later",
        "factor-bound number theory smoke computed 83*97=8051 and znorder(Mod(3,7))=6",
        "8051 crosschecked by integer multiplication; order 6 crosschecked as phi(7)",
    )


def _probe_maxima() -> A08ToolProbe:
    exe = _which(("maxima",))
    if exe is None:
        return _wait("maxima", "maxima executable not found on PATH", "GPL-2.0-only")
    proc = _run(
        (
            exe,
            "--very-quiet",
            "--batch-string="
            "display2d:false$ print(factor(x^4-1))$ "
            "print(expand((x-1)*(x+1)*(x^2+1)))$ quit();",
        )
    )
    output = proc.stdout.replace(" ", "")
    if proc.returncode != 0 or "(x-1)*(x+1)*(x^2+1)" not in output or "x^4-1" not in output:
        return _wait("maxima", f"Maxima smoke failed: {proc.stderr or proc.stdout}", "GPL-2.0-only")
    return _active(
        "maxima",
        exe,
        _version(exe, ("--version",)),
        "GPL-2.0-only",
        "symbolic algebra smoke factored x^4-1",
        "expanded returned factors back to x^4-1",
    )


def _probe_gap() -> A08ToolProbe:
    exe = _which(("gap",))
    if exe is None:
        return _wait("gap", "gap executable not found on PATH", "GPL-2.0-or-later")
    proc = _run(
        (exe, "-q"),
        stdin=(
            'g := Group((1,2,3),(1,2));; Print(Size(g), "\\n"); Print(IsAbelian(g), "\\n"); QUIT;\n'
        ),
    )
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if proc.returncode != 0 or lines != ["6", "false"]:
        return _wait("gap", f"GAP smoke failed: {proc.stderr or proc.stdout}", "GPL-2.0-or-later")
    return _active(
        "gap",
        exe,
        _gap_version(exe),
        "GPL-2.0-or-later",
        "finite-group smoke computed S3 generated by (1,2,3) and (1,2)",
        "group size 6 and non-abelian result crosschecked against S3",
    )


def _probe_singular() -> A08ToolProbe:
    exe = _which(("Singular", "singular"))
    if exe is None:
        return _wait("singular", "Singular executable not found on PATH", "GPL-2.0-or-later")
    script = (
        "ring r=0,(x,y),dp; poly f=x^2-y^2; factorize(f); ideal I=x^2-y,xy-1; groebner(I); quit;\n"
    )
    proc = _run((exe, "-q", "--no-rc"), stdin=script)
    output = proc.stdout.replace(" ", "")
    has_factor = "x-y" in output and "x+y" in output
    has_groebner = "y2-x" in output and "xy-1" in output and "x2-y" in output
    if proc.returncode != 0 or not (has_factor and has_groebner):
        return _wait(
            "singular",
            f"Singular smoke failed: {proc.stderr or proc.stdout}",
            "GPL-2.0-or-later",
        )
    return _active(
        "singular",
        exe,
        _version(exe, ("--version",)),
        "GPL-2.0-or-later",
        "polynomial smoke factorized x^2-y^2 and computed a Groebner basis",
        "factors x-y/x+y and basis generators crosschecked in output",
    )


def _probe_z3_native() -> A08ToolProbe:
    exe = _which(("z3",))
    if exe is None:
        return _wait("z3-native", "z3 executable not found on PATH", "MIT")
    proc = _run(
        (exe, "-in"),
        stdin=(
            "(set-logic QF_LIA)\n(declare-const x Int)\n(assert (> x 1))\n"
            "(assert (< x 3))\n(check-sat)\n"
        ),
    )
    if proc.returncode != 0 or _first_line(proc.stdout) != "sat":
        return _wait("z3-native", f"native z3 smoke failed: {proc.stderr or proc.stdout}", "MIT")
    return _active(
        "z3-native",
        exe,
        _version(exe, ("-version",)),
        "MIT",
        "native SMT-LIB smoke solved bounded integer formula as sat",
        "same formula has unique integer witness x=2 by inspection",
    )


def _probe_cvc5_native() -> A08ToolProbe:
    exe = _which(("cvc5",))
    if exe is None:
        return _wait("cvc5", "cvc5 executable not found on PATH", "BSD-3-Clause")
    proc = _run(
        (exe, "--lang", "smt2", "--incremental"),
        stdin=(
            "(set-logic QF_LIA)\n(declare-const x Int)\n(assert (> x 1))\n"
            "(assert (< x 3))\n(check-sat)\n"
        ),
    )
    if proc.returncode != 0 or _first_line(proc.stdout) != "sat":
        return _wait(
            "cvc5",
            f"native cvc5 smoke failed: {proc.stderr or proc.stdout}",
            "BSD-3-Clause",
        )
    return _active(
        "cvc5",
        exe,
        _version(exe, ("--version",)),
        "BSD-3-Clause",
        "native SMT-LIB smoke solved bounded integer formula as sat",
        "Z3/cvc5 agreement corpus includes this QF_LIA formula",
    )
