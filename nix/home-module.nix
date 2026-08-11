# Home Manager module for the host where the windows appear.
#
# Declares the configuration file, the session services and the launchers, so `waypipe-desktop
# generate` is never needed: a switch puts all three in place and removes the ones you dropped.

self:
{
    config,
    lib,
    pkgs,
    ...
}:
let
    cfg = config.programs.waypipe-desktop;

    exe = lib.getExe cfg.package;

    # Matches waypipe-desktop's own rule, so the unit a launcher starts is the unit declared here
    unitName =
        host:
        "waypipe-session-"
        + lib.stringAsChars (
            c:
            if lib.hasInfix c "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" then c else "-"
        ) host;

    usedHosts = lib.unique (lib.mapAttrsToList (_: app: app.host) cfg.apps);

    hostOptions =
        { name, ... }:
        {
            options = {
                ssh = lib.mkOption {
                    type = lib.types.str;
                    default = name;
                    description = "SSH destination to reach this host at, when the attribute name is a label rather than a destination.";
                };

                xdgDataDirs = lib.mkOption {
                    type = lib.types.nullOr lib.types.str;
                    default = null;
                    example = "/usr/share";
                    description = "Portal search path used on this host. Null lets waypipe-desktop derive one covering a Nix profile and an FHS distribution at once.";
                };

                flags = lib.mkOption {
                    type = lib.types.nullOr (lib.types.listOf lib.types.str);
                    default = null;
                    description = "Waypipe flags for this host alone. Null uses {option}`programs.waypipe-desktop.flags`.";
                };
            };
        };

    appOptions =
        { name, ... }:
        {
            options = {
                title = lib.mkOption {
                    type = lib.types.str;
                    default = name;
                    description = "Name shown in the app grid.";
                };

                host = lib.mkOption {
                    type = lib.types.str;
                    example = "workstation";
                    description = "SSH destination to run the application on, or an attribute name from {option}`programs.waypipe-desktop.hosts`.";
                };

                command = lib.mkOption {
                    type = lib.types.listOf lib.types.str;
                    example = [
                        "firefox"
                        "--new-instance"
                    ];
                    description = "Argv of the remote program, resolved on the remote host's PATH.";
                };

                environment = lib.mkOption {
                    type = lib.types.attrsOf lib.types.str;
                    default = { };
                    example = {
                        GDK_BACKEND = "wayland";
                    };
                    description = "Environment variables set for the remote program.";
                };

                # A path, because the app is not installed here and so neither is its themed icon
                icon = lib.mkOption {
                    type = lib.types.either lib.types.str lib.types.path;
                    default = name;
                    description = "Icon file shipped beside the app's module, or a name from the local theme.";
                };

                categories = lib.mkOption {
                    type = lib.types.listOf lib.types.str;
                    default = [ "Utility" ];
                    description = "Freedesktop categories for the launcher.";
                };

                audio = lib.mkOption {
                    type = lib.types.bool;
                    default = false;
                    description = "Play the app's sound here rather than out of the remote host's speakers.";
                };

                audioLatency = lib.mkOption {
                    type = lib.types.nullOr lib.types.ints.positive;
                    default = null;
                    example = 400;
                    description = "Milliseconds of audio buffered ahead, trading delay for tolerance of a jittery link. Null leaves the audio server's own default.";
                };
            };
        };

    settings =
        {
            session =
                {
                    inherit (cfg) flags;
                    socket-dir = cfg.socketDir;
                }
                // lib.optionalAttrs (cfg.sessionName != null) { name = cfg.sessionName; };

            apps = lib.mapAttrs (
                _: app:
                {
                    inherit (app)
                        title
                        host
                        command
                        environment
                        categories
                        audio
                        ;

                    # Interpolated rather than toString'd, so an icon shipped beside its module is copied into the store
                    icon = "${app.icon}";
                }
                // lib.optionalAttrs (app.audioLatency != null) { audio-latency = app.audioLatency; }
            ) cfg.apps;
        }
        // lib.optionalAttrs (cfg.hosts != { }) {
            hosts = lib.mapAttrs (
                _: host:
                { inherit (host) ssh; }
                // lib.optionalAttrs (host.xdgDataDirs != null) { xdg-data-dirs = host.xdgDataDirs; }
                // lib.optionalAttrs (host.flags != null) { inherit (host) flags; }
            ) cfg.hosts;
        };
in
{
    options.programs.waypipe-desktop = {
        enable = lib.mkEnableOption "waypipe-desktop, and the sessions and launchers it implies";

        package = lib.mkOption {
            type = lib.types.package;
            default = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
            defaultText = lib.literalExpression "waypipe-desktop.packages.\${system}.default";
            description = "The waypipe-desktop package to use.";
        };

        sessionName = lib.mkOption {
            type = lib.types.nullOr lib.types.str;
            default = null;
            description = "Names the sockets on the remote host. Null uses this machine's hostname, lowercased.";
        };

        flags = lib.mkOption {
            type = lib.types.listOf lib.types.str;
            # Measured on a laptop driving a phone over wifi: DMABUF costs 3x the CPU for fewer frames, and zstd beats lz4 because sshd is the scarcer resource
            default = [
                "--no-gpu"
                "--compress"
                "zstd=1"
            ];
            description = "Waypipe flags applied to each session, so tuning changes in one place.";
        };

        socketDir = lib.mkOption {
            type = lib.types.str;
            default = "/tmp";
            description = "Directory the display, bus and audio sockets are created in on the remote host.";
        };

        hosts = lib.mkOption {
            type = lib.types.attrsOf (lib.types.submodule hostOptions);
            default = { };
            description = "Per-host settings, for the cases where one host differs. Hosts an app names are usable without an entry here.";
        };

        apps = lib.mkOption {
            type = lib.types.attrsOf (lib.types.submodule appOptions);
            default = { };
            description = "Applications run on another host and displayed on this one.";
        };
    };

    config = lib.mkIf cfg.enable {
        assertions = [
            {
                assertion = lib.all (host: lib.elem host usedHosts) (lib.attrNames cfg.hosts);
                message =
                    "programs.waypipe-desktop.hosts names hosts that no app runs on, so their settings "
                    + "would never apply: "
                    + lib.concatStringsSep ", " (lib.subtractLists usedHosts (lib.attrNames cfg.hosts));
            }
        ];

        home.packages = [ cfg.package ];

        xdg.configFile."waypipe-desktop/config.toml".source =
            (pkgs.formats.toml { }).generate "waypipe-desktop.toml" settings;

        xdg.desktopEntries = lib.mapAttrs' (
            key: app:
            lib.nameValuePair "waypipe-${key}" {
                name = app.title;
                exec = "${exe} run ${key}";
                icon = app.icon;
                categories = app.categories;
                terminal = false;
            }
        ) cfg.apps;

        systemd.user.services = lib.listToAttrs (
            map (
                host:
                lib.nameValuePair (unitName host) {
                    Unit = {
                        Description = "Shared waypipe session on ${host}";
                        After = [ "graphical-session.target" ];
                        PartOf = [ "graphical-session.target" ];

                        # Without a limit the 5s restart never trips systemd's default, so an unreachable host would be retried forever
                        StartLimitBurst = 3;
                        StartLimitIntervalSec = 60;
                    };

                    # No Install section: a launcher starts this on demand, so a boot with the other host off does not retry forever
                    Service = {
                        ExecStart = "${exe} session ${host}";

                        # Start blocks until ExecStartPost returns, so the app never races the display it is about to connect to
                        ExecStartPost = "${exe} wait ${host}";
                        Restart = "on-failure";
                        RestartSec = 5;
                    };
                }
            ) usedHosts
        );
    };
}
