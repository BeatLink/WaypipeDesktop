"""Loads waypipe-desktop's TOML configuration into hosts, apps and socket paths.

The host key is the ssh destination unless a [hosts.<key>] table overrides it, so a
configuration that only lists apps is complete.
"""

from __future__ import annotations

import os
import re
import socket
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_ENV = "WAYPIPE_DESKTOP_CONFIG"

# Measured on a laptop to a phone over wifi: DMABUF costs 3x the CPU for fewer frames, and zstd beats lz4 because sshd is the scarcer resource
DEFAULT_FLAGS = ["--no-gpu", "--compress", "zstd=1"]

# Every entry that does not exist is ignored, so one list covers a Nix profile, a per-user profile and an FHS distribution at once
DEFAULT_REMOTE_XDG_DATA_DIRS = ""


class ConfigError(Exception):
    """Raised when the configuration is missing, malformed or internally inconsistent."""


@dataclass(frozen=True)
class Host:
    """One remote host, and the session settings that differ from the defaults."""

    key: str
    ssh: str
    xdg_data_dirs: str = DEFAULT_REMOTE_XDG_DATA_DIRS
    flags: list[str] | None = None

    @property
    def unit(self) -> str:
        """Name of the systemd user service holding this host's session open."""
        return f"waypipe-session-{_slug(self.key)}.service"


@dataclass(frozen=True)
class App:
    """One application run on a remote host and displayed on this one."""

    key: str
    title: str
    host: str
    command: list[str]
    environment: dict[str, str] = field(default_factory=dict)
    icon: str = ""
    categories: list[str] = field(default_factory=lambda: ["Utility"])
    audio: bool = False
    audio_latency: int | None = None


@dataclass(frozen=True)
class Config:
    """A whole configuration file, resolved and validated."""

    path: Path
    session: str
    flags: list[str]
    socket_dir: str
    hosts: dict[str, Host]
    apps: dict[str, App]

    @property
    def display_socket(self) -> str:
        """Wayland socket the session serves on the remote host."""
        return f"{self.socket_dir}/waypipe-{self.session}-display"

    @property
    def bus_socket(self) -> str:
        """Session bus socket the leader serves on the remote host."""
        return f"{self.socket_dir}/waypipe-{self.session}-bus"

    @property
    def audio_socket(self) -> str:
        """PulseAudio socket forwarded to the remote host."""
        return f"{self.socket_dir}/waypipe-{self.session}-audio"

    def host(self, key: str) -> Host:
        """Host named by key, defaulting to one whose ssh destination is the key itself."""
        return self.hosts.get(key) or Host(key=key, ssh=key)

    def app(self, key: str) -> App:
        """App named by key, or a ConfigError naming the ones that exist."""
        if key not in self.apps:
            known = ", ".join(sorted(self.apps)) or "none"
            raise ConfigError(f"no app named {key!r} in {self.path} (known: {known})")
        return self.apps[key]

    def app_hosts(self) -> list[str]:
        """Host keys that at least one app runs on, in a stable order."""
        return sorted({app.host for app in self.apps.values()})

    def flags_for(self, host: Host) -> list[str]:
        """Waypipe flags for one host, falling back to the session-wide ones."""
        return self.flags if host.flags is None else host.flags


def _slug(value: str) -> str:
    """Rewrites a host key into something systemd will accept as a unit name."""
    return re.sub(r"[^A-Za-z0-9_.-]", "-", value)


def search_path() -> list[Path]:
    """Files consulted for a configuration, in the order they are tried."""
    candidates = []
    if override := os.environ.get(CONFIG_ENV):
        candidates.append(Path(override))
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    candidates.append(Path(xdg) / "waypipe-desktop" / "config.toml")
    candidates.append(Path("/etc/waypipe-desktop/config.toml"))
    return candidates


def load(path: Path | None = None) -> Config:
    """Reads the first configuration that exists, or the one given."""
    chosen = path or next((c for c in search_path() if c.is_file()), None)
    if chosen is None:
        tried = ", ".join(str(c) for c in search_path())
        raise ConfigError(f"no configuration file found (tried: {tried})")
    try:
        raw = tomllib.loads(chosen.read_text())
    except OSError as error:
        raise ConfigError(f"cannot read {chosen}: {error}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"cannot parse {chosen}: {error}") from error
    return _parse(chosen, raw)


def _parse(path: Path, raw: dict) -> Config:
    """Turns a parsed TOML document into a validated Config."""
    _reject_unknown(raw, {"session", "hosts", "apps"}, "top level")

    session = _table(raw, "session")
    _reject_unknown(session, {"name", "flags", "socket-dir"}, "[session]")

    hosts = {
        key: _parse_host(key, table) for key, table in _table(raw, "hosts").items()
    }
    apps = {key: _parse_app(key, table) for key, table in _table(raw, "apps").items()}

    config = Config(
        path=path,
        session=_string(session, "name", socket.gethostname().split(".")[0].lower()),
        flags=_strings(session, "flags", DEFAULT_FLAGS),
        socket_dir=_string(session, "socket-dir", "/tmp"),
        hosts=hosts,
        apps=apps,
    )
    _check_references(config)
    return config


def _parse_host(key: str, table: dict) -> Host:
    """Reads one [hosts.<key>] table."""
    _reject_unknown(table, {"ssh", "xdg-data-dirs", "flags"}, f"[hosts.{key}]")
    flags = table.get("flags")
    return Host(
        key=key,
        ssh=_string(table, "ssh", key),
        xdg_data_dirs=_string(table, "xdg-data-dirs", DEFAULT_REMOTE_XDG_DATA_DIRS),
        flags=None if flags is None else _strings(table, "flags", []),
    )


def _parse_app(key: str, table: dict) -> App:
    """Reads one [apps.<key>] table."""
    where = f"[apps.{key}]"
    _reject_unknown(
        table,
        {
            "title",
            "host",
            "command",
            "environment",
            "icon",
            "categories",
            "audio",
            "audio-latency",
        },
        where,
    )

    host = _string(table, "host", "")
    if not host:
        raise ConfigError(f"{where} needs a host to run on")

    command = _strings(table, "command", [])
    if not command:
        raise ConfigError(f"{where} needs a command to run")

    latency = table.get("audio-latency")
    if latency is not None and (not isinstance(latency, int) or latency <= 0):
        raise ConfigError(f"{where}.audio-latency must be a positive whole number")

    environment = table.get("environment", {})
    if not isinstance(environment, dict) or not all(
        isinstance(v, str) for v in environment.values()
    ):
        raise ConfigError(f"{where}.environment must map names to strings")

    return App(
        key=key,
        title=_string(table, "title", key),
        host=host,
        command=command,
        environment=environment,
        icon=_string(table, "icon", key),
        categories=_strings(table, "categories", ["Utility"]),
        audio=_boolean(table, "audio", False),
        audio_latency=latency,
    )


def _check_references(config: Config) -> None:
    """Fails when a [hosts.<key>] table is defined that no app ever names."""
    orphans = sorted(set(config.hosts) - set(config.app_hosts()))
    if orphans:
        raise ConfigError(
            "these hosts are configured but no app runs on them, so their settings "
            f"would never apply: {', '.join(orphans)}"
        )


def _table(raw: dict, name: str) -> dict:
    """Reads a table, treating an absent one as empty."""
    value = raw.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] must be a table")
    return value


def _string(table: dict, name: str, default: str) -> str:
    """Reads a string field."""
    value = table.get(name, default)
    if not isinstance(value, str):
        raise ConfigError(f"{name} must be a string")
    return value


def _strings(table: dict, name: str, default: list[str]) -> list[str]:
    """Reads a list-of-strings field."""
    value = table.get(name, default)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{name} must be a list of strings")
    return list(value)


def _boolean(table: dict, name: str, default: bool) -> bool:
    """Reads a boolean field."""
    value = table.get(name, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{name} must be true or false")
    return value


def _reject_unknown(table: dict, allowed: set[str], where: str) -> None:
    """Fails on a key that is not recognised, so a typo is not silently ignored."""
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise ConfigError(
            f"{where} has unrecognised keys: {', '.join(unknown)} "
            f"(known: {', '.join(sorted(allowed))})"
        )
