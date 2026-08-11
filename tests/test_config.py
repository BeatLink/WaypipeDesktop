"""Covers configuration parsing, validation and the socket paths derived from it."""

import pytest

from waypipe_desktop import config as configuration

MINIMAL = """
[session]
name = "thor"

[apps.firefox-odin]
title = "Firefox (Odin)"
host = "odin-waypipe"
command = ["firefox", "--profile", "/home/beatlink/Personal"]
audio = true
audio-latency = 400
environment = { GDK_BACKEND = "wayland" }
"""


def write(tmp_path, text):
    """Writes a configuration file and returns its path."""
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_defaults_and_sockets(tmp_path):
    loaded = configuration.load(write(tmp_path, MINIMAL))
    assert loaded.session == "thor"
    assert loaded.flags == configuration.DEFAULT_FLAGS
    assert loaded.display_socket == "/tmp/waypipe-thor-display"
    assert loaded.bus_socket == "/tmp/waypipe-thor-bus"
    assert loaded.audio_socket == "/tmp/waypipe-thor-audio"


def test_app_fields(tmp_path):
    app = configuration.load(write(tmp_path, MINIMAL)).app("firefox-odin")
    assert app.host == "odin-waypipe"
    assert app.audio_latency == 400
    assert app.environment == {"GDK_BACKEND": "wayland"}
    assert app.categories == ["Utility"]
    assert app.icon == "firefox-odin"


def test_host_key_is_the_ssh_destination_by_default(tmp_path):
    host = configuration.load(write(tmp_path, MINIMAL)).host("odin-waypipe")
    assert host.ssh == "odin-waypipe"
    assert host.unit == "waypipe-session-odin-waypipe.service"


def test_host_table_overrides(tmp_path):
    text = MINIMAL + """
[hosts.odin-waypipe]
ssh = "beatlink@10.0.0.2"
xdg-data-dirs = "/usr/share"
flags = ["--compress", "lz4"]
"""
    loaded = configuration.load(write(tmp_path, text))
    host = loaded.host("odin-waypipe")
    assert host.ssh == "beatlink@10.0.0.2"
    assert host.xdg_data_dirs == "/usr/share"
    assert loaded.flags_for(host) == ["--compress", "lz4"]


def test_unit_name_is_sanitised(tmp_path):
    text = """
[apps.editor]
host = "beatlink@10.0.0.2"
command = ["kate"]
"""
    host = configuration.load(write(tmp_path, text)).host("beatlink@10.0.0.2")
    assert host.unit == "waypipe-session-beatlink-10.0.0.2.service"


@pytest.mark.parametrize(
    "text",
    [
        '[apps.x]\ncommand = ["a"]\n',
        '[apps.x]\nhost = "h"\n',
        '[apps.x]\nhost = "h"\ncommand = ["a"]\naudio-latency = 0\n',
        '[apps.x]\nhost = "h"\ncommand = ["a"]\ntitel = "typo"\n',
        '[session]\nnaem = "typo"\n',
        '[apps.x]\nhost = "h"\ncommand = ["a"]\n[hosts.unused]\nssh = "y"\n',
    ],
)
def test_rejects_bad_configuration(tmp_path, text):
    with pytest.raises(configuration.ConfigError):
        configuration.load(write(tmp_path, text))


def test_missing_app_names_the_known_ones(tmp_path):
    loaded = configuration.load(write(tmp_path, MINIMAL))
    with pytest.raises(configuration.ConfigError, match="firefox-odin"):
        loaded.app("nope")


def test_missing_file_lists_the_search_path(tmp_path, monkeypatch):
    monkeypatch.delenv(configuration.CONFIG_ENV, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    with pytest.raises(configuration.ConfigError, match="waypipe-desktop/config.toml"):
        configuration.load()
