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
    Allocates 64 MiB memory slabs until the ``RLIMIT_AS`` cap raises
    ``MemoryError`` (Linux), then sleeps forever so the wall watchdog kills the
    group. On macOS the cap is best-effort and the same watchdog backstop
    applies. Used by the memory-bomb case.
``forker.v1``
    Forks repeatedly until ``RLIMIT_NPROC`` stops it. Used by the fork-bomb
    case. Each child exits immediately so no long-lived fan-out survives.
``chatter.v1``
    Writes a large payload to stdout to exceed the output cap. Used by the
    output-cap case.
``netcanary.v1``
    Attempts a TCP ``connect`` to the reserved, non-routable TEST-NET-1 address
    ``192.0.2.1`` and reports the attempt. Used by the WP-D34 network canary:
    the assertion is observational — the attempt is *recorded* — not that the
    sandbox blocked it (network denial on macOS CI is not guaranteed). The
    target is RFC 5737 documentation space and must never be reachable.
``cwdprobe.v1``
    Returns the child's current working directory and platform. Used by the
    WP-D34 hardening check to assert the child CWD is the scratch dir, not the
    parent repo root.
``setsiddler.v1``
    Forks a child that calls :func:`os.setsid` to escape the process group, then
    lingers briefly. Used by the WP-D34 setsid-evasion detector: a final
    process-group sweep by name must observe no survivor after the watchdog
    kills the leader. The lingering child exits quickly so no real orphan leaks.
``invalidout.v1``
    A deliberately schema-invalid output adapter. It returns a dict with an extra
    field that is not allowed by its declared output schema, so the runner's
    output validation rejects it and writes no receipt. Used by the WP-D34
    schema-invalid-output case.

None of these perform network I/O against a real target (``netcanary.v1`` aims
only at RFC 5737 reserved space). They are standard library only.
"""

from __future__ import annotations

import os
import socket
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
    """Allocate memory in 64 MiB slabs until the RLIMIT_AS cap is hit.

    On Linux ``RLIMIT_AS`` (policy ``rss_bytes``) raises ``MemoryError`` once the
    virtual-address budget is exhausted. The handler catches that and sleeps
    forever so the run is bounded by the wall watchdog, which classifies the
    outcome as ``TIMEOUT`` with ``fail_reason=RESOURCE_LIMIT``. On macOS the cap
    is best-effort and the same sleep loop is reached either by the cap or by the
    slab budget; in either case the run never returns cleanly and no receipt is
    written.
    """
    del payload  # the bomb takes no parameters
    blocks: list[bytearray] = []
    slab = 64 * 1024 * 1024  # 64 MiB
    # Allocate enough slabs to exhaust the M1 policy's 1.5 GiB RLIMIT_AS cap
    # on Linux (24 * 64 MiB = 1.5 GiB). A small pause between slabs keeps the
    # host responsive and prevents runaway allocation on macOS where the cap
    # is best-effort. If the cap fires early, break out and wait for the
    # watchdog; do not exit with a clean contract code.
    for _ in range(24):
        try:
            blocks.append(bytearray(slab))
        except (MemoryError, OSError):
            break
        time.sleep(0.05)
    while True:
        time.sleep(0.2)
    # Unreachable; kept for the type checker.


def _forker_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """Fork repeatedly until ``RLIMIT_NPROC`` stops the fan-out.

    The fan-out is bounded by the sandbox ``RLIMIT_NPROC=256`` cap. Once the
    cap fires (``os.fork`` raises ``OSError`` / ``EAGAIN``), the parent stays
    alive and does NOT return a clean output -- it sleeps in a tight loop so
    the runner's wall watchdog kills the whole process group. The runner then
    classifies the run as ``timeout`` with ``fail_reason=RESOURCE_LIMIT`` and
    writes no receipt.

    Children stay alive long enough to keep the live process count at the cap,
    so the cap is genuinely exercised. The runner reaps the parent; any children
    that were not reaped before the group kill are cleaned up by the watchdog's
    ``killpg``.
    """
    target = payload.get("count", 8192)
    if not isinstance(target, int) or target < 0:
        target = 8192
    pids: list[int] = []
    for _ in range(target):
        try:
            pid = os.fork()
        except OSError:
            # RLIMIT_NPROC hit (EAGAIN). Keep the parent alive so the runner
            # wall-times out the group; do not return a clean output.
            while True:
                time.sleep(0.2)
        if pid == 0:
            # Child: stay alive long enough to consume the NPROC budget until
            # the watchdog kills the group.
            time.sleep(30)
            os._exit(0)
        else:
            pids.append(pid)
    # Reached target without hitting the cap: still do not return a clean run.
    while True:
        time.sleep(0.2)


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


# The reserved, non-routable TEST-NET-1 address (RFC 5737). It is documentation
# space and must never correspond to a real host; a connect to it hangs or is
# refused depending on the local network posture. Used only by netcanary.v1.
_NETCANARY_HOST: Final[str] = "192.0.2.1"
_NETCANARY_PORT: Final[int] = 1


def _netcanary_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """Attempt a TCP connect to ``192.0.2.1`` (TEST-NET-1); report the attempt.

    This is the WP-D34 network canary vehicle. The assertion the gate makes is
    *observational*: the attempt was made and recorded. Whether the connect
    succeeded, timed out, or was refused depends on the host network posture
    and is NOT asserted (macOS CI does not guarantee network denial). The target
    is RFC 5737 reserved space and must never be reachable in practice.

    The handler always returns a dict recording ``attempted=True`` and the
    observed outcome, so the case is hermetic regardless of network state.
    """
    del payload  # the canary takes no parameters
    attempted = True
    outcome = "unknown"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            sock.connect((_NETCANARY_HOST, _NETCANARY_PORT))
        outcome = "connected"
    except TimeoutError:
        outcome = "timeout"
    except OSError as exc:
        # Refused, unreachable, or network-denied. errno is recorded so the
        # gate can observe the local posture without asserting it.
        outcome = f"oserror:{exc.errno}"
    return {
        "attempted": attempted,
        "target": f"{_NETCANARY_HOST}:{_NETCANARY_PORT}",
        "outcome": outcome,
    }


def _cwdprobe_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the child's CWD and platform (the WP-D34 cwd-isolation probe).

    The runner sets the child's working directory to the scratch dir (never the
    parent repo root). This handler returns :func:`os.getcwd` so the gate can
    assert the child did NOT inherit the orchestrator's CWD.
    """
    del payload
    return {"cwd": os.getcwd(), "platform": sys.platform, "pid": os.getpid()}


def _setsiddler_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """Fork a child that escapes the process group via :func:`os.setsid`.

    The grandchild calls ``setsid`` (becoming its own session/group leader) so
    a naive ``killpg(leader_pid)`` would miss it. It lingers briefly so a
    post-kill sweep by name can observe it; the handler reaps it before
    returning so no real orphan leaks out of the test. Used by the WP-D34
    setsid-evasion detector: the sweep must find (and clear) any survivor.
    """
    linger = payload.get("linger", 2)
    if not isinstance(linger, int) or linger < 0:
        linger = 2
    spawned = False
    setsid_ok = False
    try:
        pid = os.fork()
    except OSError:
        pid = -1
    if pid == 0:
        # Grandchild: try to escape the group, then linger briefly and exit.
        try:
            os.setsid()
            setsid_ok = True
        except OSError:
            setsid_ok = False
        time.sleep(linger)
        os._exit(0)
    elif pid > 0:
        spawned = True
        # The parent handler returns immediately; the watchdog kills the leader
        # (this handler's process), and the grandchild — now in its own group —
        # is the setsid-evader the sweep must catch. We reap it here so the test
        # does not leave a live orphan; the sweep runs *before* this reap in the
        # gate's ordered sequence.
        try:
            os.kill(pid, 15)
        except OSError:
            pass
        try:
            os.waitpid(pid, 0)
        except OSError:
            pass
    return {"spawned_grandchild": spawned, "setsid_attempted": True, "setsid_ok": setsid_ok}


def _invalidout_handler(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a schema-invalid output dict (the WP-D34 invalid-output vehicle).

    The input is a valid string under ``text``. The output contains the same
    string plus an extra ``invalid`` boolean field that is not declared in the
    adapter's output schema, so the runner's output validation rejects it and
    classifies the run as ``failed`` with no receipt written.
    """
    text = payload.get("text", "ok")
    if not isinstance(text, str):
        text = "ok"
    return {"text": text, "invalid": True}


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
_NETCANARY_V1: Final[AdapterDescriptor] = AdapterDescriptor(
    adapter_id="netcanary.v1",
    version="v1",
    handler=_netcanary_handler,
    input_schema={"required": [], "optional": []},
    output_schema={"required": [], "optional": ["attempted", "target", "outcome"]},
    deterministic=True,
)
_CWDPROBE_V1: Final[AdapterDescriptor] = AdapterDescriptor(
    adapter_id="cwdprobe.v1",
    version="v1",
    handler=_cwdprobe_handler,
    input_schema={"required": [], "optional": []},
    output_schema={"required": [], "optional": ["cwd", "platform", "pid"]},
    deterministic=True,
)
_SETSIDDLER_V1: Final[AdapterDescriptor] = AdapterDescriptor(
    adapter_id="setsiddler.v1",
    version="v1",
    handler=_setsiddler_handler,
    input_schema={"required": [], "optional": ["linger"]},
    output_schema={
        "required": [],
        "optional": ["spawned_grandchild", "setsid_attempted", "setsid_ok"],
    },
    deterministic=True,
)
_INVALIDOUT_V1: Final[AdapterDescriptor] = AdapterDescriptor(
    adapter_id="invalidout.v1",
    version="v1",
    handler=_invalidout_handler,
    input_schema={"required": ["text"], "optional": [], "types": {"text": "str"}},
    output_schema={"required": ["text"], "optional": [], "types": {"text": "str"}},
    deterministic=True,
)

ADAPTERS.update(
    {
        _SLEEPER_V1.adapter_id: _SLEEPER_V1,
        _BOMB_V1.adapter_id: _BOMB_V1,
        _FORKER_V1.adapter_id: _FORKER_V1,
        _CHATTER_V1.adapter_id: _CHATTER_V1,
        _NETCANARY_V1.adapter_id: _NETCANARY_V1,
        _CWDPROBE_V1.adapter_id: _CWDPROBE_V1,
        _SETSIDDLER_V1.adapter_id: _SETSIDDLER_V1,
        _INVALIDOUT_V1.adapter_id: _INVALIDOUT_V1,
    }
)
