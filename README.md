# waypipe-desktop

Run Wayland applications from another host and have them appear on this one, as ordinary entries in
your app grid.

[waypipe](https://gitlab.freedesktop.org/mstoeckl/waypipe) already forwards a single Wayland
application over ssh. waypipe-desktop turns that into a desktop: one shared session per remote host,
so every app you launch from that host lands on the same display, talks to the same session bus, sees
the same portal stack, opens one instance rather than one per launch, and can play its sound through
your speakers instead of the remote machine's.

Nothing has to be installed on the remote host beyond `waypipe` and `dbus-daemon`.

## Contents

- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Commands](#commands)
- [Setting up the remote host](#setting-up-the-remote-host)
- [Tuning](#tuning)
- [On NixOS](#on-nixos)
- [Using it from another configuration manager](#using-it-from-another-configuration-manager)
- [Troubleshooting](#troubleshooting)

## How it works

Each remote host gets one systemd user service. Its `ExecStart` is a waypipe session whose remote
command is a `dbus-daemon` serving a session bus:

```
waypipe --no-gpu --compress zstd=1 --display /tmp/waypipe-<session>-display \
    ssh -R /tmp/waypipe-<session>-audio:$XDG_RUNTIME_DIR/pulse/native <host> \
        env XDG_DATA_DIRS=... GDK_BACKEND=wayland \
            dbus-daemon --session --address=unix:path=/tmp/waypipe-<session>-bus --nofork --nopidfile
```

The session's lifetime *is* that bus. The bus is the remote command, so the display lives exactly as
long as the link, and when the link dies the unit fails rather than hanging on to every window.

Launching an app is then just ssh into the same three sockets:

```
ssh <host> env WAYLAND_DISPLAY=<display> DBUS_SESSION_BUS_ADDRESS=unix:path=<bus> \
    PULSE_SERVER=unix:<audio> firefox
```

Two details make it reliable:

- `ExecStartPost` polls for the bus socket on the far side, and `systemctl start` blocks until it
  returns — so an app never races the display it is about to join.
- Before opening a session, the previous one is reaped. sshd does not kill the remote command when a
  link drops, so without this a restart would orphan the old bus and strand every app attached to it.

Sockets live under `/tmp` at absolute paths, named after *this* host, so nothing has to resolve the
remote host's uid or runtime directory, and two machines can drive the same remote host at once.

## Requirements

**Locally:** Python 3.11+, `waypipe`, `ssh`, systemd (user instance), a Wayland compositor, and
PipeWire or PulseAudio if you want remote apps to use your speakers.

**On the remote host:** `waypipe` and `dbus-daemon` on a *non-login* `PATH`, plus `pkill` and an
sshd that accepts key authentication.

Both ends need compatible waypipe versions. waypipe refuses a mismatched wire version, so if a
session dies immediately, compare `waypipe --version` on the two hosts first.

## Installation

With Nix:

```
nix run github:BeatLink/WaypipeDesktop -- list
```

or add the flake as an input and install `packages.${system}.default`.

Otherwise, from a checkout:

```
pip install --user .
```

## Configuration

waypipe-desktop reads the first file that exists out of:

1. `$WAYPIPE_DESKTOP_CONFIG`
2. `$XDG_CONFIG_HOME/waypipe-desktop/config.toml` (usually `~/.config/waypipe-desktop/config.toml`)
3. `/etc/waypipe-desktop/config.toml`

or whatever `--config` names.

```toml
[session]
# Names the sockets on the remote host. Defaults to this machine's hostname, lowercased.
name = "laptop"

# Applied to every session unless a host overrides them.
flags = ["--no-gpu", "--compress", "zstd=1"]

# Where the display, bus and audio sockets are created on the remote host.
socket-dir = "/tmp"

[apps.firefox-remote]
title = "Firefox (Remote)"                 # shown in the app grid
host = "workstation-waypipe"               # ssh destination, or a key from [hosts]
command = ["firefox", "--profile", "/home/me/Personal"]
icon = "/usr/share/icons/firefox.png"      # icon file, or a name from the local theme
categories = ["Network", "WebBrowser"]
audio = true                               # play its sound here rather than on the remote host
audio-latency = 400                        # ms buffered ahead, trading delay for a jittery link
environment = { GDK_BACKEND = "wayland" }
```

`host` is used as the ssh destination directly, so for most setups that is all you need. A `[hosts]`
table exists only for the cases where something about one host differs:

```toml
[hosts.desktop]
ssh = "me@10.0.0.2"             # when the key is a label rather than a destination
xdg-data-dirs = "/usr/share"    # override the portal search path used on that host
flags = ["--compress", "lz4"]   # override the session flags for that host alone
```

An app then reaches that host with `host = "desktop"`.

Unrecognised keys are an error rather than being ignored, so a typo shows up the first time you run
`waypipe-desktop list` instead of silently doing nothing.

### `audio-latency`

waypipe carries Wayland alone, so without `audio = true` a video plays its picture here and its sound
on the remote machine. With it, PulseAudio is forwarded over the same ssh connection.

Set `audio-latency` to roughly the worst round trip you expect. On a stable LAN the default is fine;
on mobile data, values around 400 ms stop the stream breaking up when latency swings.

## Commands

| Command | What it does |
| --- | --- |
| `waypipe-desktop list` | Show the resolved sockets, hosts and apps |
| `waypipe-desktop generate` | Write the systemd user services and desktop entries |
| `waypipe-desktop run <app>` | Start the app's session if needed, then launch the app |
| `waypipe-desktop session <host>` | Hold a host's session open — this is a unit's `ExecStart` |
| `waypipe-desktop wait <host>` | Block until a host's session bus answers — a unit's `ExecStartPost` |

`generate` owns the files it writes (`waypipe-session-*.service` and `waypipe-*.desktop`) and deletes
the ones that are no longer configured, so removing an app from the config and re-running it removes
the launcher too. Run it after every configuration change.

Sessions are started on demand by `run`, never at login: a boot with the other host switched off
should not spend the morning retrying.

## Setting up the remote host

This part is deliberately not automated — it changes sshd and your keys, which belongs to whatever
manages that host.

1. **A dedicated key.** Generate one just for this and point ssh at it, so it never displaces your
   agent key on a plain `ssh <host>`:

   ```
   ssh-keygen -t ed25519 -f ~/.ssh/waypipe -C waypipe
   ```

   ```
   # ~/.ssh/config
   Host workstation-waypipe
       HostName workstation.example
       User me
       IdentityFile ~/.ssh/waypipe
       IdentitiesOnly yes
   ```

   Add the public key to the remote user's `~/.ssh/authorized_keys`. Key auth is required: every
   connection runs with `BatchMode=yes` and will never prompt.

2. **Let the audio forward rebind.** A forwarded Unix socket is left behind when the link drops, and
   sshd refuses to bind over an existing one, so the next launch would come up silent. On the remote
   host:

   ```
   # /etc/ssh/sshd_config
   StreamLocalBindUnlink yes
   ```

3. **Check the portal path.** Remote apps find their portals through `XDG_DATA_DIRS`, which a
   non-login ssh session does not set. waypipe-desktop builds a default covering a Nix profile, a
   per-user profile and an FHS distribution at once; if your host puts them somewhere else, set
   `xdg-data-dirs` for it.

## Tuning

The defaults — `--no-gpu --compress zstd=1` — were measured on a laptop driving a phone over wifi.
DMABUF cost three times the CPU for fewer frames, and zstd beat lz4 because sshd was the scarcer
resource. Run `waypipe bench` between your own hosts before changing them; on a fast link with slow
CPUs the answer is different.

## On NixOS

Two modules are shipped, one per end of the link. Both are optional; the tool works from a plain
`config.toml` without either.

### The machine the windows appear on

`homeModules.default` is a Home Manager module. It writes the configuration file *and* declares the
session services and launchers, so `generate` is never needed — a switch puts all three in place and
removes the ones you dropped.

```nix
{
  inputs.waypipe-desktop.url = "github:BeatLink/WaypipeDesktop";

  # …in your Home Manager configuration:
  imports = [ inputs.waypipe-desktop.homeModules.default ];

  programs.waypipe-desktop = {
    enable = true;

    apps.firefox-remote = {
      title = "Firefox (Remote)";
      host = "workstation-waypipe";
      command = [ "firefox" "--profile" "/home/me/Personal" ];
      icon = ./firefox.png;          # a path is copied into the store
      categories = [ "Network" "WebBrowser" ];
      audio = true;
      audioLatency = 400;
      environment.GDK_BACKEND = "wayland";
    };
  };
}
```

Options mirror the TOML in camelCase: `sessionName`, `flags`, `socketDir`, `hosts.<name>.{ssh,
xdgDataDirs, flags}` and `apps.<name>.{title, host, command, environment, icon, categories, audio,
audioLatency}`. `package` defaults to this flake's build. A `hosts` entry that no app names is an
assertion failure rather than a setting that silently does nothing.

### The machine the applications run on

`nixosModules.default` covers the far side, which needs no waypipe-desktop of its own:

```nix
{
  imports = [ inputs.waypipe-desktop.nixosModules.default ];

  services.waypipe-desktop = {
    enable = true;
    user = "me";
    authorizedKeys = [ "ssh-ed25519 AAAA… waypipe" ];
  };
}
```

That installs `waypipe` and `dbus` system-wide — a non-login ssh session resolves them on the system
PATH, not the user's — sets `StreamLocalBindUnlink` so the audio forward can rebind, and adds the key.

Where two machines run each other's applications, enable both modules on both.

`overlays.default` provides `pkgs.waypipe-desktop` if you would rather not go through the modules.

## Using it from another configuration manager

If something else already writes systemd units and desktop entries declaratively, skip `generate` and
have it write them itself. The contract is small:

- one service per host, `ExecStart=waypipe-desktop session <host>` and
  `ExecStartPost=waypipe-desktop wait <host>`, `Restart=on-failure`, `RestartSec=5`, and a start
  limit so an unreachable host is not retried forever — but **no `[Install]` section**;
- one desktop entry per app, `Exec=waypipe-desktop run <app>`;
- a `config.toml` holding the same apps.

`waypipe-desktop generate` is the reference for exactly what those files look like.

## Troubleshooting

**The session fails immediately.** `journalctl --user -u waypipe-session-<host> -e`. The usual
causes are a waypipe version mismatch, `waypipe` or `dbus-daemon` not being on the remote non-login
`PATH` (check with `ssh <host> command -v waypipe dbus-daemon`), or key auth not working under
`BatchMode`.

**An app starts but no window appears.** It probably picked X11. Set `GDK_BACKEND=wayland`,
`QT_QPA_PLATFORM=wayland`, or for Electron `NIXOS_OZONE_WL=1`, in the app's `environment`.

**A second launch does nothing.** That is usually the point — the app is already running on the
shared session and raised its existing window. Where you want a genuinely separate instance, give it
its own profile or data directory in `command`.

**No sound.** Check `audio = true`, then that `StreamLocalBindUnlink` is set on the remote host, then
that `$XDG_RUNTIME_DIR/pulse/native` exists here.

**Portal dialogs appear on the remote machine's screen.** Its `XDG_DATA_DIRS` is resolving to that
host's own session. Set `xdg-data-dirs` for the host explicitly.

## License

GPL-3.0-only.
