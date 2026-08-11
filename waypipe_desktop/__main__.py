"""Command line entry point for waypipe-desktop."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config as configuration
from . import generate as generation
from . import launch, session


def main(argv: list[str] | None = None) -> int:
    """Parses arguments, loads the configuration and runs the chosen subcommand."""
    arguments = _parser().parse_args(argv)
    try:
        loaded = configuration.load(arguments.config)
        return arguments.handler(loaded, arguments)
    except (
        configuration.ConfigError,
        session.SessionError,
        launch.LaunchError,
        RuntimeError,
    ) as error:
        print(f"waypipe-desktop: {error}", file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    """Builds the argument parser and binds each subcommand to its handler."""
    parser = argparse.ArgumentParser(
        prog="waypipe-desktop",
        description="Run Wayland applications from another host inside one shared session per host.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="configuration file to use instead of the first one on the search path",
    )
    subcommands = parser.add_subparsers(dest="subcommand", required=True)

    open_session = subcommands.add_parser("session", help="hold a host's shared session open")
    open_session.add_argument("host")
    open_session.set_defaults(handler=_session)

    wait = subcommands.add_parser("wait", help="block until a host's session bus answers")
    wait.add_argument("host")
    wait.set_defaults(handler=_wait)

    run = subcommands.add_parser("run", help="run a configured app on its host")
    run.add_argument("app")
    run.set_defaults(handler=_run)

    listing = subcommands.add_parser("list", help="show the configured hosts and apps")
    listing.set_defaults(handler=_list)

    write = subcommands.add_parser(
        "generate", help="write the systemd user services and desktop entries"
    )
    write.set_defaults(handler=_generate)

    return parser


def _session(loaded: configuration.Config, arguments) -> int:
    """Holds one host's session open, replacing this process with waypipe."""
    session.open_session(loaded, loaded.host(arguments.host))
    return 0


def _wait(loaded: configuration.Config, arguments) -> int:
    """Waits for one host's session bus to answer."""
    session.wait_for_session(loaded, loaded.host(arguments.host))
    return 0


def _run(loaded: configuration.Config, arguments) -> int:
    """Launches one app, replacing this process with the ssh that carries it."""
    launch.run_app(loaded, loaded.app(arguments.app))
    return 0


def _list(loaded: configuration.Config, arguments) -> int:
    """Prints the session's sockets, its hosts and its apps."""
    print(f"config   {loaded.path}")
    print(f"session  {loaded.session}")
    print(f"display  {loaded.display_socket}")
    print(f"bus      {loaded.bus_socket}")
    print(f"audio    {loaded.audio_socket}")
    for key in loaded.app_hosts():
        host = loaded.host(key)
        print(f"\nhost {key} -> {host.ssh} ({host.unit})")
        for app in sorted(loaded.apps.values(), key=lambda a: a.key):
            if app.host == key:
                sound = " audio" if app.audio else ""
                print(f"  {app.key:<24} {app.title}{sound}")
    return 0


def _generate(loaded: configuration.Config, arguments) -> int:
    """Writes the units and launchers the configuration implies."""
    for path in generation.generate(loaded):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
