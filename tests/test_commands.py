"""Covers the commands built for the remote host and the files generate writes."""

import pytest

from waypipe_desktop import config as configuration
from waypipe_desktop import generate as generation
from waypipe_desktop import launch, session

TEXT = """
[session]
name = "laptop"

[apps.firefox-remote]
title = "Firefox (Remote)"
host = "workstation"
command = ["firefox", "--profile", "/home/me/My Profile"]
icon = "/nix/store/abc/firefox.png"
categories = ["Network", "WebBrowser"]
audio = true
audio-latency = 400
environment = { GDK_BACKEND = "wayland" }

[apps.editor]
title = "Editor"
host = "quiet-host"
command = ["kate"]
"""


@pytest.fixture
def loaded(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(TEXT)
    return configuration.load(path)


def test_remote_argv_joins_the_session(loaded):
    argv = launch.remote_argv(loaded, loaded.app("firefox-remote"))
    assert argv[0] == "env"
    assert "WAYLAND_DISPLAY=/tmp/waypipe-laptop-display" in argv
    assert "DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/waypipe-laptop-bus" in argv
    assert "PULSE_SERVER=unix:/tmp/waypipe-laptop-audio" in argv
    assert "PULSE_LATENCY_MSEC=400" in argv
    assert "GDK_BACKEND=wayland" in argv
    assert argv[-3:] == ["firefox", "--profile", "/home/me/My Profile"]


def test_remote_argv_leaves_audio_out_when_unused(loaded):
    argv = launch.remote_argv(loaded, loaded.app("editor"))
    assert not any(word.startswith("PULSE_") for word in argv)


def test_session_argv_carries_no_shell_metacharacters(loaded, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    argv = session.session_argv(loaded, loaded.host("workstation"), "/home/me", "me")
    assert argv[:2] == ["waypipe", "--no-gpu"]
    assert "--display" in argv and "/tmp/waypipe-laptop-display" in argv
    assert "-R" in argv
    assert "/tmp/waypipe-laptop-audio:/run/user/1000/pulse/native" in argv
    assert argv[argv.index("workstation") + 1] == "env"
    assert argv[-1] == "--nopidfile"
    assert not any(set(word) & set("|&;<>()$`\\\"' \t\n") for word in argv)


def test_session_argv_omits_the_audio_forward_when_no_app_needs_it(loaded):
    argv = session.session_argv(loaded, loaded.host("quiet-host"), "/home/me", "me")
    assert "-R" not in argv


def test_data_dirs_cover_nix_and_fhs(loaded):
    argv = session.session_argv(loaded, loaded.host("quiet-host"), "/home/me", "me")
    dirs = next(word for word in argv if word.startswith("XDG_DATA_DIRS="))
    assert "/home/me/.nix-profile/share" in dirs
    assert "/etc/profiles/per-user/me/share" in dirs
    assert "/usr/share" in dirs


def test_generate_writes_and_prunes(loaded, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(generation, "_executable", lambda: "/bin/waypipe-desktop")
    monkeypatch.setattr(generation, "_reload", lambda: None)

    units = tmp_path / "config" / "systemd" / "user"
    applications = tmp_path / "data" / "applications"
    units.mkdir(parents=True)
    stale = units / "waypipe-session-gone.service"
    stale.write_text("")

    generation.generate(loaded)

    assert not stale.exists()
    unit = (units / "waypipe-session-workstation.service").read_text()
    assert "ExecStart=/bin/waypipe-desktop session workstation" in unit
    assert "ExecStartPost=/bin/waypipe-desktop wait workstation" in unit
    assert "[Install]" not in unit

    entry = (applications / "waypipe-firefox-remote.desktop").read_text()
    assert "Exec=/bin/waypipe-desktop run firefox-remote" in entry
    assert "Categories=Network;WebBrowser;" in entry
    assert "Icon=/nix/store/abc/firefox.png" in entry
