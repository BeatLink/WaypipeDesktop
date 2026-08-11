# Evaluates both modules against a sample configuration, so an option that stops type checking fails here.
#
# The Home Manager module is evaluated against stubs of the four options it writes to, rather than
# against Home Manager itself, so checking it costs this flake no extra input.
{
    lib,
    nixpkgs,
    pkgs,
    self,
}:
let
    sample = {
        sessionName = "laptop";
        hosts.workstation = {
            ssh = "me@10.0.0.2";
            xdgDataDirs = "/usr/share";
            flags = [
                "--compress"
                "lz4"
            ];
        };
        apps = {
            firefox = {
                title = "Firefox (Remote)";
                host = "workstation";
                command = [
                    "firefox"
                    "--profile"
                    "/home/me/Personal"
                ];
                categories = [
                    "Network"
                    "WebBrowser"
                ];
                environment.GDK_BACKEND = "wayland";
                audio = true;
                audioLatency = 400;
            };
            editor = {
                host = "me@10.0.0.3";
                command = [ "kate" ];
            };
        };
    };

    # Stands in for the Home Manager options the module writes to, typed loosely because only the module's own logic is under test
    stubs =
        { ... }:
        {
            options = {
                home.packages = lib.mkOption {
                    type = lib.types.listOf lib.types.package;
                    default = [ ];
                };
                xdg.configFile = lib.mkOption {
                    type = lib.types.attrsOf lib.types.anything;
                    default = { };
                };
                xdg.desktopEntries = lib.mkOption {
                    type = lib.types.attrsOf lib.types.anything;
                    default = { };
                };
                systemd.user.services = lib.mkOption {
                    type = lib.types.attrsOf lib.types.anything;
                    default = { };
                };
                assertions = lib.mkOption {
                    type = lib.types.listOf lib.types.anything;
                    default = [ ];
                };
            };
        };

    home =
        (lib.evalModules {
            modules = [
                stubs
                self.homeModules.default
                {
                    _module.args.pkgs = pkgs;
                    programs.waypipe-desktop = { enable = true; } // sample;
                }
            ];
        }).config;

    nixos =
        (nixpkgs.lib.nixosSystem {
            modules = [
                self.nixosModules.default
                {
                    nixpkgs.hostPlatform = pkgs.stdenv.hostPlatform.system;
                    boot.loader.grub.devices = [ "/dev/null" ];
                    fileSystems."/" = {
                        device = "/dev/null";
                        fsType = "ext4";
                    };
                    system.stateVersion = "25.05";
                    users.users.me.isNormalUser = true;

                    services.waypipe-desktop = {
                        enable = true;
                        user = "me";
                        authorizedKeys = [ "ssh-ed25519 AAAAsample waypipe" ];
                    };
                }
            ];
        }).config;

    # Reduced to strings before forcing, because deepSeq over a derivation walks the whole package graph
    summary = {
        assertions = map (a: a.assertion) (home.assertions ++ nixos.assertions);
        config = "${home.xdg.configFile."waypipe-desktop/config.toml".source}";
        launchers = lib.mapAttrs (_: entry: entry.exec) home.xdg.desktopEntries;
        units = lib.mapAttrs (_: unit: unit.Service.ExecStart) home.systemd.user.services;
        packages = map (package: package.name) home.home.packages;
        remotePackages = lib.filter (name: lib.hasPrefix "waypipe-" name || lib.hasPrefix "dbus-" name) (
            map (package: package.name) nixos.environment.systemPackages
        );
        rebind = nixos.services.openssh.settings.StreamLocalBindUnlink;
        keys = nixos.users.users.me.openssh.authorizedKeys.keys;
    };
in
pkgs.runCommand "waypipe-desktop-modules" { summary = builtins.toJSON summary; } ''
    printf '%s\n' "$summary" > $out
''
