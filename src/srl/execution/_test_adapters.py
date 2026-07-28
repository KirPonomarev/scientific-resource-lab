"""Test-only adapters for the WP-D31 gate and unit tests.

This module is **not** part of the production adapter registry. It is loaded
only when ``SRL_RUNNER_TEST_ADAPTERS=1`` is set in the environment (see
:func:`srl.execution.entrypoints._test_adapters`), which happens exclusively in
the WP-D31 gate and the runner unit tests. A production run — any run without
that env var — never imports this module and sees only the shipped
``{echo.v1, uppercase.v1}`` registry.

The adapters here exist to exercise the sandbox's enforcement paths:

``sleeper.v1``
    Sleeps for the number of seconds in ``seconds`` (default 10). Used by the
    timeout case (a child that runs past its wall cap) and the orphan check.
``bomb.v1``
    Allocates memory until it is killed (by ``RLIMIT_AS`` on Linux, or by the
    wall watchdog elsewhere). Used by the memory-bomb case.
``forker.v1``
    Forks repeatedly until ``RLIMIT_NPROC`` stops it. Used by the fork-bomb
    case. Each child exits immediately so no long-lived fan-out survives.
``chatter.v1``
    Writes a large payload to stdout to exceed the output cap. Used by the
    output-cap case.

None of these perform network I/O. They are standard library only.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Final

from srl.execution.entrypoints import AdapterDescriptor

# Module-level constant the entrypoints hook reads. Kept as a plain dict so the
# hook can merge it without a copy; the hook does its own snapshot.
ADAPTERS: Final[dict[str, AdapterDescriptor]] = {}


def _sleeper_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """Sleep for ``payload['seconds']`` (default 10); return how long it slept.

    The sleep is bounded by the runner's wall watchdog — this handler is the
    vehicle for the timeout case, so it intentionally runs past the wall cap.
    """
    seconds = payload.get("seconds", 10)
    if not isinstance(seconds, int) or seconds < 0:
        seconds = 10
    time.sleep(seconds)
    return {"slept": seconds}


def _bomb_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """Allocate memory in 64 MiB slabs until killed.

    On Linux (CI) ``RLIMIT_AS`` kills the process; elsewhere the wall watchdog
    does. The handler never returns normally — it is the memory-bomb vehicle.
    """
    del payload  # the bomb takes no parameters
    blocks: list[bytearray] = []
    slab = 64 * 1024 * 1024  # 64 MiB
    while True:
        blocks.append(bytearray(slab))
    # Unreachable; kept for the type checker.


def _forker_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """Fork repeatedly until ``RLIMIT_NPROC`` stops the fan-out.

    Children sleep briefly so they stay live and the live-process count climbs
    to the ``RLIMIT_NPROC`` cap, at which point :func:`os.fork` raises
    ``OSError`` (``EAGAIN``). The handler is the fork-bomb vehicle: it does NOT
    reap mid-loop, so the cap is genuinely exercised. After the loop it reaps
    what it can so the watchdog's orphan check stays clean.
    """
    target = payload.get("count", 1024)
    if not isinstance(target, int) or target < 0:
        target = 1024
    pids: list[int] = []
    for _ in range(target):
        try:
            pid = os.fork()
        except OSError:
            # RLIMIT_NPROC hit (EAGAIN) — the expected stop. Break and report.
            break
        if pid == 0:
            # Child: stay alive briefly so the live count climbs to the cap.
            time.sleep(2)
            os._exit(0)
        else:
            pids.append(pid)
    # Reap what we can before returning so the orphan check is not polluted by
    # our own intentional short-lived children.
    for pid in pids:
        try:
            os.kill(pid, 15)
        except OSError:
            pass
        try:
            os.waitpid(pid, 0)
        except OSError:
            pass
    return {"forked": len(pids)}


def _chatter_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """Write a large payload to stdout to exceed the output cap.

    The size comes from ``payload['bytes']`` (default 4 MiB, well over the 1 MiB
    default cap). The handler writes to ``sys.stdout`` and flushes, so the
    capped reader observes the over-cap stream and the runner kills the child.
    """
    size = payload.get("bytes", 4 * 1024 * 1024)
    if not isinstance(size, int) or size < 0:
        size = 4 * 1024 * 1024
    chunk = b"x" * 4096
    written = 0
    out = sys.stdout.buffer
    while written < size:
        n = min(4096, size - written)
        out.write(chunk[:n])
        written += n
    out.flush()
    return {"wrote": written}


_SLEEPER_V1: Final[AdapterDescriptor] = AdapterDescriptor(
    adapter_id="sleeper.v1",
    version="v1",
    handler=_sleeper_handler,
    input_schema={"required": [], "optional": ["seconds"]},
    output_schema={"required": [], "optional": ["slept"]},
    deterministic=True,
)
_BOMB_V1: Final[AdapterDescriptor] = AdapterDescriptor(
    adapter_id="bomb.v1",
    version="v1",
    handler=_bomb_handler,
    input_schema={"required": [], "optional": []},
    output_schema={"required": [], "optional": ["bytes"]},
    deterministic=True,
)
_FORKER_V1: Final[AdapterDescriptor] = AdapterDescriptor(
    adapter_id="forker.v1",
    version="v1",
    handler=_forker_handler,
    input_schema={"required": [], "optional": ["count"]},
    output_schema={"required": [], "optional": ["forked"]},
    deterministic=True,
)
_CHATTER_V1: Final[AdapterDescriptor] = AdapterDescriptor(
    adapter_id="chatter.v1",
    version="v1",
    handler=_chatter_handler,
    input_schema={"required": [], "optional": ["bytes"]},
    output_schema={"required": [], "optional": ["wrote"]},
    deterministic=True,
)

ADAPTERS.update(
    {
        _SLEEPER_V1.adapter_id: _SLEEPER_V1,
        _BOMB_V1.adapter_id: _BOMB_V1,
        _FORKER_V1.adapter_id: _FORKER_V1,
        _CHATTER_V1.adapter_id: _CHATTER_V1,
    }
)
