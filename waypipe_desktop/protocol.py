"""The commands one host sends the other, built in one place so the far side can recognise them.

A key restricted to a forced command has to decide whether what arrived is a session's own traffic.
Building and matching from the same functions is what keeps those two answers in step.
"""

from __future__ import annotations

import shlex

READY_TRIES = 60
READY_INTERVAL = "0.2"


def display_socket(socket_dir: str, session: str) -> str:
    """Wayland socket the session serves on the remote host."""
    return f"{socket_dir}/waypipe-{session}-display"


def bus_socket(socket_dir: str, session: str) -> str:
    """Session bus socket the leader serves on the remote host."""
    return f"{socket_dir}/waypipe-{session}-bus"


def audio_socket(socket_dir: str, session: str) -> str:
    """PulseAudio socket forwarded to the remote host."""
    return f"{socket_dir}/waypipe-{session}-audio"


def prepare_script(display: str, bus: str) -> str:
    """Clears the previous session off the remote host and reports its home directory and user."""
    # sshd does not reap the remote command when the link drops, so without this a restart orphans
    # the previous bus and strands every app still attached to it
    return "; ".join(
        [
            f"pkill -f {shlex.quote('^dbus-daemon --session --address=unix:path=' + bus)} || true",
            f"pkill -f {shlex.quote('^waypipe .*--display ' + display)} || true",
            f"rm -f {shlex.quote(display)} {shlex.quote(bus)}",
            'printf "%s\\n%s\\n" "$HOME" "$(id -un)"',
        ]
    )


def poll_script(bus: str) -> str:
    """Waits on the far side for the session bus to appear, so waiting costs one connection."""
    return (
        f"for _ in $(seq {READY_TRIES}); do "
        f"if test -S {shlex.quote(bus)}; then exit 0; fi; "
        f"sleep {READY_INTERVAL}; done; exit 1"
    )


def leader_argv(bus: str) -> list[str]:
    """Remote command serving the session bus, whose lifetime is the session's own."""
    return [
        "dbus-daemon",
        "--session",
        f"--address=unix:path={bus}",
        "--nofork",
        "--nopidfile",
    ]
