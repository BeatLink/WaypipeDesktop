"""Opens, reaps and waits on the one waypipe session shared by every app on a host.

The session's lifetime is the bus it serves: dbus-daemon runs as the remote command, so the
display lives exactly as long as the link, and nothing has to be installed on the far side.
"""

from __future__ import annotations

import os
import shlex
import subprocess

from .config import Config, Host

# Turns a dead link into a unit failure, rather than a session that hangs holding every window
SSH_KEEPALIVE = ["-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3"]

READY_TRIES = 60
READY_INTERVAL = "0.2"


class SessionError(Exception):
    """Raised when a session cannot be prepared, opened or waited on."""


def open_session(config: Config, host: Host) -> None:
    """Replaces this process with the waypipe session for one host, after clearing the last one."""
    home, user = _prepare(config, host)
    argv = session_argv(config, host, home, user)
    os.execvp(argv[0], argv)


def session_argv(config: Config, host: Host, home: str, user: str) -> list[str]:
    """Full waypipe invocation for one host's session."""
    forward = (
        ["-R", f"{config.audio_socket}:{_local_pulse_socket()}"]
        if _needs_audio(config, host)
        else []
    )
    return [
        "waypipe",
        *config.flags_for(host),
        "--display",
        config.display_socket,
        "ssh",
        *forward,
        *SSH_KEEPALIVE,
        host.ssh,
        *_leader_argv(config, host, home, user),
    ]


def wait_for_session(config: Config, host: Host) -> None:
    """Blocks until the session's bus answers, so an app never races the display it is about to join."""
    # Polls on the far side, so waiting for the bus costs one connection rather than one per attempt
    poll = (
        f"for _ in $(seq {READY_TRIES}); do "
        f"if test -S {shlex.quote(config.bus_socket)}; then exit 0; fi; "
        f"sleep {READY_INTERVAL}; done; exit 1"
    )
    if _ssh(host.ssh, poll).returncode != 0:
        raise SessionError(f"the session bus on {host.ssh} never appeared")


def _prepare(config: Config, host: Host) -> tuple[str, str]:
    """Clears the previous session off the remote host and reports its home directory and user."""
    # sshd does not reap the remote command when the link drops, so without this a restart orphans
    # the previous bus and strands every app still attached to it
    script = "; ".join(
        [
            f"pkill -f {shlex.quote('^dbus-daemon --session --address=unix:path=' + config.bus_socket)} || true",
            f"pkill -f {shlex.quote('^waypipe .*--display ' + config.display_socket)} || true",
            f"rm -f {shlex.quote(config.display_socket)} {shlex.quote(config.bus_socket)}",
            'printf "%s\\n%s\\n" "$HOME" "$(id -un)"',
        ]
    )
    result = _ssh(host.ssh, script, capture=True)
    if result.returncode != 0:
        raise SessionError(f"cannot reach {host.ssh}: {(result.stderr or '').strip()}")

    reported = result.stdout.split()
    if len(reported) != 2:
        raise SessionError(f"{host.ssh} did not report its home directory and user")
    return reported[0], reported[1]


def _leader_argv(config: Config, host: Host, home: str, user: str) -> list[str]:
    """Remote command serving the session bus, as plain argv so no quoting has to survive the trip."""
    return [
        "env",
        f"XDG_DATA_DIRS={host.xdg_data_dirs or _default_data_dirs(home, user)}",
        # GDK would otherwise pick X11 and draw the portal's dialogs on the remote host's own screen
        "GDK_BACKEND=wayland",
        # No --systemd-activation, so dbus spawns each portal from its Exec= line and the child inherits this display
        "dbus-daemon",
        "--session",
        f"--address=unix:path={config.bus_socket}",
        "--nofork",
        "--nopidfile",
    ]


def _default_data_dirs(home: str, user: str) -> str:
    """Search path a portal is found on, covering a Nix profile and an FHS distribution at once."""
    # ssh runs no login shell, so without this dbus finds no portal service file and every portal call times out
    return ":".join(
        [
            f"{home}/.nix-profile/share",
            f"/etc/profiles/per-user/{user}/share",
            "/run/current-system/sw/share",
            "/usr/local/share",
            "/usr/share",
        ]
    )


def _needs_audio(config: Config, host: Host) -> bool:
    """Whether any app on this host plays its sound here rather than out of the remote speakers."""
    return any(app.audio for app in config.apps.values() if app.host == host.key)


def _local_pulse_socket() -> str:
    """Path of this host's PulseAudio socket, which the session forwards to the remote host."""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        raise SessionError("XDG_RUNTIME_DIR is unset, so the audio socket cannot be located")
    return f"{runtime}/pulse/native"


def _ssh(destination: str, command: str, capture: bool = False) -> subprocess.CompletedProcess:
    """Runs one command on a remote host without ever prompting for input."""
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", destination, command],
        capture_output=capture,
        text=True,
        check=False,
    )
