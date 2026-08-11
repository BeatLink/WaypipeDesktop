{
    description = "waypipe-desktop - run Wayland applications from another host inside one shared session per host";

    inputs = {
        nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
        flake-utils.url = "github:numtide/flake-utils";
    };

    outputs =
        {
            self,
            nixpkgs,
            flake-utils,
        }:
        flake-utils.lib.eachDefaultSystem (
            system:
            let
                pkgs = nixpkgs.legacyPackages.${system};
                python = pkgs.python3;

                # Resolved at run time rather than closure-tracked, so the wrapper has to put them on PATH itself
                runtimeInputs = with pkgs; [
                    openssh
                    waypipe
                    systemd
                ];
            in
            {
                packages.default = python.pkgs.buildPythonApplication {
                    pname = "waypipe-desktop";
                    version = "0.1.0";
                    src = ./.;
                    format = "pyproject";

                    nativeBuildInputs = [ python.pkgs.setuptools ];
                    makeWrapperArgs = [ "--prefix PATH : ${pkgs.lib.makeBinPath runtimeInputs}" ];

                    nativeCheckInputs = [ python.pkgs.pytest ];
                    checkPhase = "pytest";

                    meta = {
                        description = "Run Wayland applications from another host inside one shared session per host";
                        mainProgram = "waypipe-desktop";
                        license = pkgs.lib.licenses.gpl3Only;
                        platforms = pkgs.lib.platforms.linux;
                    };
                };

                apps.default = {
                    type = "app";
                    program = "${self.packages.${system}.default}/bin/waypipe-desktop";
                };

                devShells.default = pkgs.mkShell {
                    buildInputs = [
                        (python.withPackages (ps: [ ps.pytest ]))
                    ] ++ runtimeInputs;
                };
            }
        );
}
