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
            ];

            environment.systemPackages = cfg.packages;

            services.openssh.enable = lib.mkDefault true;

            # An audio forward leaves its socket file behind, and sshd refuses to bind over one, so the next launch would come up silent
            services.openssh.settings.StreamLocalBindUnlink = true;
        })

        (lib.mkIf (cfg.enable && cfg.user != null) {
            users.users.${cfg.user}.openssh.authorizedKeys.keys = cfg.authorizedKeys;
        })
    ];
}
