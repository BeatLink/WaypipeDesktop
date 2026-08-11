{
    description = "waypipe-desktop - run Wayland applications from another host inside one shared session per host";

    inputs = {
        nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    };

    outputs =
        { self, nixpkgs }:
        let
            # Wayland and waypipe are Linux only, so there is nothing to offer the other platforms
            systems = [
                "x86_64-linux"
                "aarch64-linux"
            ];

            forAllSystems = function: nixpkgs.lib.genAttrs systems (system: function nixpkgs.legacyPackages.${system});
        in
        {
            packages = forAllSystems (pkgs: {
                default = pkgs.callPackage ./nix/package.nix { };
            });

            apps = forAllSystems (pkgs: {
                default = {
                    type = "app";
                    program = "${self.packages.${pkgs.stdenv.hostPlatform.system}.default}/bin/waypipe-desktop";
                };
            });

            devShells = forAllSystems (pkgs: {
                default = pkgs.mkShell {
                    inputsFrom = [ self.packages.${pkgs.stdenv.hostPlatform.system}.default ];
                    packages = [ pkgs.python3.pkgs.pytest ];
                };
            });
        };
}
