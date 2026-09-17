# NixOS module for the host the applications actually run on.
#
# The far side needs no waypipe-desktop of its own; what it needs is waypipe and dbus on a non-login
# PATH, an sshd that will rebind the audio socket, and a key to let the other machine in.

self:
{
    config,
    lib,
    pkgs,
    ...
}:
let
    cfg = config.services.waypipe-desktop;

    policy = (pkgs.formats.json { }).generate "waypipe-desktop-policy.json" {
        socket_dir = cfg.socketDir;
        inherit (cfg) sessions;
        apps = map (app: { inherit (app) command environment; }) cfg.apps;
    };

    # Options ride in front of the key itself, which is where authorized_keys takes them
    keyOptions =
        lib.optionals cfg.restrict [
            "restrict"
            "port-forwarding"
        ]
        ++ lib.optional (
            cfg.sessions != [ ]
        ) ''command="${lib.getExe cfg.package} gatekeeper --policy ${policy}"'';
in
{
    options.services.waypipe-desktop = {
        enable = lib.mkEnableOption "accepting waypipe-desktop sessions from another host";

        user = lib.mkOption {
            type = lib.types.nullOr lib.types.str;
            default = null;
            example = "me";
            description = "User the applications run as, and whose authorized keys {option}`authorizedKeys` are added to.";
        };

        authorizedKeys = lib.mkOption {
            type = lib.types.listOf lib.types.str;
            default = [ ];
            description = "Public keys allowed to open a session, which should be dedicated to waypipe rather than shared with your agent key.";
        };

        restrict = lib.mkOption {
            type = lib.types.bool;
            default = true;
            description = ''
                Whether to take away everything a session does not use: agent and X11 forwarding, pty
                allocation and user rc. Port forwarding is kept, because the audio socket travels over it.
            '';
        };

        sessions = lib.mkOption {
            type = lib.types.listOf lib.types.str;
            default = [ ];
            example = [ "laptop" ];
            description = ''
                Session names whose sockets these keys may serve, as each displaying host calls itself.

                Naming any turns the keys into a forced command: what arrives is run only when it is one of
                those sessions' own commands or an app in {option}`apps`, so a key that opens a session
                cannot also be a shell. Left empty, the keys run whatever they are sent.
            '';
        };

        socketDir = lib.mkOption {
            type = lib.types.str;
            default = "/tmp";
            description = "Directory the session sockets are created in, matching the displaying host's setting.";
        };

        apps = lib.mkOption {
            type = lib.types.listOf (
                lib.types.submodule {
                    options = {
                        command = lib.mkOption {
                            type = lib.types.listOf lib.types.str;
                            description = "Argv this key may run, matched whole.";
                        };

                        environment = lib.mkOption {
                            type = lib.types.listOf lib.types.str;
                            default = [ ];
                            description = "Variable names this app may be given, on top of the ones the session sets itself.";
                        };
                    };
                }
            );
            default = [ ];
            description = "Applications the keys may launch, which is every app the displaying host declares.";
        };

        package = lib.mkOption {
            type = lib.types.package;
            default = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
            defaultText = lib.literalExpression "waypipe-desktop.packages.\${system}.default";
            description = "The waypipe-desktop package whose gatekeeper decides what a restricted key may run.";
        };

        packages = lib.mkOption {
            type = lib.types.listOf lib.types.package;
            default = with pkgs; [
                waypipe
                dbus
            ];
            defaultText = lib.literalExpression "[ pkgs.waypipe pkgs.dbus ]";
            description = "Installed system-wide, because a non-login ssh session resolves them on the system PATH rather than the user's own.";
        };
    };

    config = lib.mkMerge [
        (lib.mkIf cfg.enable {
            assertions = [
                {
                    assertion = cfg.authorizedKeys == [ ] || cfg.user != null;
                    message = "services.waypipe-desktop.authorizedKeys needs services.waypipe-desktop.user to say whose keys they are.";
                }
                {
                    assertion = cfg.apps == [ ] || cfg.sessions != [ ];
                    message = "services.waypipe-desktop.apps only takes effect with services.waypipe-desktop.sessions set, which is what turns the keys into a forced command.";
                }
            ];

            environment.systemPackages = cfg.packages;

            services.openssh.enable = lib.mkDefault true;

            # An audio forward leaves its socket file behind, and sshd refuses to bind over one, so the next launch would come up silent
            services.openssh.settings.StreamLocalBindUnlink = true;
        })

        (lib.mkIf (cfg.enable && cfg.user != null) {
            users.users.${cfg.user}.openssh.authorizedKeys.keys = map (
                key: lib.optionalString (keyOptions != [ ]) (lib.concatStringsSep "," keyOptions + " ") + key
            ) cfg.authorizedKeys;
        })
    ];
}
