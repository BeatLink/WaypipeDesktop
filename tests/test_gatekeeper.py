"""Covers what a key restricted to the gatekeeper will and will not run."""

import pytest

from waypipe_desktop import gatekeeper, protocol

POLICY = {
    "socket_dir": "/tmp",
    "sessions": ["laptop"],
    "apps": [
        {"command": ["firefox", "--profile", "/home/me/My Profile"], "environment": ["GDK_BACKEND"]},
        {"command": ["keepassxc"]},
    ],
}

DISPLAY = protocol.display_socket("/tmp", "laptop")
BUS = protocol.bus_socket("/tmp", "laptop")


def test_prepare_script_runs():
    assert gatekeeper.resolve(protocol.prepare_script(DISPLAY, BUS), POLICY)[:2] == ["/bin/sh", "-c"]


def test_poll_script_runs():
    assert gatekeeper.resolve(protocol.poll_script(BUS), POLICY)[:2] == ["/bin/sh", "-c"]


def test_another_sessions_sockets_are_refused():
    other = protocol.bus_socket("/tmp", "desktop")
    with pytest.raises(gatekeeper.Refused):
        gatekeeper.resolve(protocol.poll_script(other), POLICY)


def test_leader_runs_with_its_own_variables():
    command = "env XDG_DATA_DIRS=/usr/share GDK_BACKEND=wayland " + " ".join(protocol.leader_argv(BUS))
    assert gatekeeper.resolve(command, POLICY)[-1] == "--nopidfile"


def test_leader_is_refused_a_preload():
    command = "env LD_PRELOAD=/tmp/evil.so " + " ".join(protocol.leader_argv(BUS))
    with pytest.raises(gatekeeper.Refused):
        gatekeeper.resolve(command, POLICY)


def test_declared_app_runs():
    command = f"env WAYLAND_DISPLAY={DISPLAY} GDK_BACKEND=wayland firefox --profile '/home/me/My Profile'"
    assert gatekeeper.resolve(command, POLICY)[-2:] == ["--profile", "/home/me/My Profile"]


def test_app_is_refused_a_variable_it_did_not_declare():
    with pytest.raises(gatekeeper.Refused):
        gatekeeper.resolve(f"env WAYLAND_DISPLAY={DISPLAY} GDK_BACKEND=wayland keepassxc", POLICY)


def test_undeclared_app_is_refused():
    with pytest.raises(gatekeeper.Refused):
        gatekeeper.resolve(f"env WAYLAND_DISPLAY={DISPLAY} bash -i", POLICY)


def test_an_apps_own_arguments_cannot_be_changed():
    with pytest.raises(gatekeeper.Refused):
        gatekeeper.resolve(f"env WAYLAND_DISPLAY={DISPLAY} firefox --profile /etc/shadow", POLICY)


def test_a_shell_is_refused():
    with pytest.raises(gatekeeper.Refused):
        gatekeeper.resolve("", POLICY)
    with pytest.raises(gatekeeper.Refused):
        gatekeeper.resolve("cat /etc/shadow", POLICY)
