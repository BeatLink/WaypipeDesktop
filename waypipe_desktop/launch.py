"""Starts an app on its remote host, bringing that host's shared session up first."""

from __future__ import annotations

import os
import shlex
import subprocess

from .config import App, Config


class LaunchError(Exception):
    """Raised when an app's session cannot be started."""


def run_app(config: Config, app: App) -> None:
    """Replaces this process with the app, running on its host inside that host's session."""
    host = config.host(app.host)

    # A session parked in failed state by the start limit would otherwise refuse every later launch
    subprocess.run(
        ["systemctl", "--user", "reset-failed", host.unit],
        check=False,
        capture_output=True,
    )

    # Start blocks until ExecStartPost returns, so the app never races the display it is about to join
    started = subprocess.run(["systemctl", "--user", "start", host.unit], check=False)
    if started.returncode != 0:
        raise LaunchError(f"could not start {host.unit}")

    argv = [
        "ssh",
        "-o",
        "BatchMode=yes",
        host.ssh,
        *(shlex.quote(word) for word in remote_argv(config, app)),
    ]
    os.execvp(argv[0], argv)


def remote_argv(config: Config, app: App) -> list[str]:
    """Command run on the remote host, joined to the session's display, bus and speakers."""
    environment = {
        "WAYLAND_DISPLAY": config.display_socket,
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path={config.bus_socket}",
    }
    if app.audio:
        environment["PULSE_SERVER"] = f"unix:{config.audio_socket}"
    if app.audio_latency is not None:
        environment["PULSE_LATENCY_MSEC"] = str(app.audio_latency)
    environment.update(app.environment)

    return ["env", *(f"{name}={value}" for name, value in environment.items()), *app.command]
