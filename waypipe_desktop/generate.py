"""Writes the systemd user services and desktop entries that the configuration implies.

Only needed where nothing else declares them; a configuration manager that writes both itself
can call the session, wait and run subcommands directly and skip this.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .config import Config, Host

DESKTOP_PREFIX = "waypipe-"
UNIT_PREFIX = "waypipe-session-"


def generate(config: Config) -> list[Path]:
    """Writes a unit per host and an entry per app, removing the ones no longer configured."""
    executable = _executable()

    units = _write(
        _units_directory(),
        f"{UNIT_PREFIX}*.service",
        {
            config.host(key).unit: _unit(config.host(key), executable)
            for key in config.app_hosts()
        },
    )
    entries = _write(
        _applications_directory(),
        f"{DESKTOP_PREFIX}*.desktop",
        {
            f"{DESKTOP_PREFIX}{app.key}.desktop": _entry(app, executable)
            for app in config.apps.values()
        },
    )

    _reload()
    return units + entries


def _write(directory: Path, owned: str, files: dict[str, str]) -> list[Path]:
    """Puts every file in place and deletes the ones this tool wrote before but no longer wants."""
    directory.mkdir(parents=True, exist_ok=True)
    for stale in directory.glob(owned):
        if stale.name not in files:
            stale.unlink()

    written = []
    for name, text in files.items():
        path = directory / name
        path.write_text(text)
        written.append(path)
    return written


def _unit(host: Host, executable: str) -> str:
    """Service holding one host's session open, started on demand by a launcher."""
    return "\n".join(
        [
            "[Unit]",
            f"Description=Shared waypipe session on {host.ssh}",
            "After=graphical-session.target",
            "PartOf=graphical-session.target",
            # Without a limit the 5s restart never trips systemd's default, so an unreachable host would be retried forever
            "StartLimitBurst=3",
            "StartLimitIntervalSec=60",
            "",
            # No [Install] section: a launcher starts this on demand, so a boot with the other host off does not retry forever
            "[Service]",
            f"ExecStart={executable} session {host.key}",
            f"ExecStartPost={executable} wait {host.key}",
            "Restart=on-failure",
            "RestartSec=5",
            "",
        ]
    )


def _entry(app, executable: str) -> str:
    """Launcher shown in the app grid for one remote application."""
    categories = "".join(f"{category};" for category in app.categories)
    return "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            f"Name={app.title}",
            f"Exec={executable.replace('%', '%%')} run {app.key}",
            f"Icon={app.icon}",
            f"Categories={categories}",
            "Terminal=false",
            "",
        ]
    )


def _executable() -> str:
    """Absolute path of this program, so a unit does not depend on systemd's PATH."""
    found = shutil.which(sys.argv[0]) or shutil.which("waypipe-desktop")
    if not found:
        raise RuntimeError("cannot locate the waypipe-desktop executable to write into units")
    return os.path.realpath(found)


def _units_directory() -> Path:
    """Directory systemd reads this user's own service files from."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user"


def _applications_directory() -> Path:
    """Directory the desktop reads this user's own launchers from."""
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "applications"


def _reload() -> None:
    """Tells systemd and the desktop to pick up what was just written."""
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    if shutil.which("update-desktop-database"):
        subprocess.run(
            ["update-desktop-database", str(_applications_directory())],
            check=False,
            capture_output=True,
        )
