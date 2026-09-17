"""Decides whether what arrived over a restricted key is one of this host's own session commands.

sshd runs this as the key's forced command, with whatever the client asked for in
SSH_ORIGINAL_COMMAND. A session's own traffic and the apps the policy names are run; anything else
is refused, so a key that can open a session cannot also be a shell.
"""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path

from . import protocol

# The session sets these itself, so they are allowed on any launch it makes
SESSION_ENVIRONMENT = {
    "WAYLAND_DISPLAY",
    "DBUS_SESSION_BUS_ADDRESS",
    "PULSE_SERVER",
    "PULSE_LATENCY_MSEC",
}

# What the leader is given, rather than what an app is
LEADER_ENVIRONMENT = {"XDG_DATA_DIRS", "GDK_BACKEND"}


class Refused(Exception):
    """Raised when the command that arrived is not one the policy allows."""


def load_policy(path: Path) -> dict:
    """Reads the policy this host was given: its session names and the apps a key may launch."""
    try:
        policy = json.loads(Path(path).read_text())
    except (OSError, ValueError) as error:
        raise Refused(f"cannot read the policy at {path}: {error}") from error

    policy.setdefault("socket_dir", "/tmp")
    policy.setdefault("sessions", [])
    policy.setdefault("apps", [])
    return policy


def resolve(command: str, policy: dict) -> list[str]:
    """Argv to replace this process with, for a command the policy allows."""
    if not command.strip():
        raise Refused("this key runs sessions and apps, not a login shell")

    # The two shell shapes are compared whole, against the same builders the client sent them from
    for session in policy["sessions"]:
        display = protocol.display_socket(policy["socket_dir"], session)
        bus = protocol.bus_socket(policy["socket_dir"], session)
        if command == protocol.prepare_script(display, bus) or command == protocol.poll_script(bus):
            return ["/bin/sh", "-c", command]

    assignments, argv = _split_environment(command)
    names = [assignment.split("=", 1)[0] for assignment in assignments]

    for session in policy["sessions"]:
        bus = protocol.bus_socket(policy["socket_dir"], session)
        if argv == protocol.leader_argv(bus):
            _check_environment(names, LEADER_ENVIRONMENT)
            return ["env", *assignments, *argv]

    for app in policy["apps"]:
        if argv == app.get("command"):
            _check_environment(names, SESSION_ENVIRONMENT | set(app.get("environment", [])))
            return ["env", *assignments, *argv]

    raise Refused(f"no session or app this key may run matches: {shlex.join(argv)}")


def run(command: str, policy: dict) -> None:
    """Replaces this process with the command, once the policy has allowed it."""
    argv = resolve(command, policy)
    os.execvp(argv[0], argv)


def _split_environment(command: str) -> tuple[list[str], list[str]]:
    """Splits an `env NAME=value ... argv` command into its assignments and the argv after them."""
    try:
        tokens = shlex.split(command)
    except ValueError as error:
        raise Refused(f"cannot read the command: {error}") from error

    if not tokens or tokens[0] != "env":
        raise Refused("a session launches through env, and nothing else may use this key")

    assignments: list[str] = []
    rest = tokens[1:]
    while rest and "=" in rest[0] and not rest[0].startswith(("-", "=")):
        assignments.append(rest[0])
        rest = rest[1:]

    if not rest:
        raise Refused("env was given no command to run")
    return assignments, rest


def _check_environment(names: list[str], allowed: set[str]) -> None:
    """Refuses any variable the policy does not name, which is what keeps LD_PRELOAD out."""
    for name in names:
        if name not in allowed:
            raise Refused(f"this key may not set {name}")
