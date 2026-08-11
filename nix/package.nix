# Packages waypipe-desktop, putting the binaries it shells out to on its own PATH.
{
    lib,
    python3Packages,
    openssh,
    systemd,
    waypipe,
}:
let
    # Resolved at run time rather than closure-tracked, so the wrapper has to put them on PATH itself
    runtimeInputs = [
        openssh
        systemd
        waypipe
    ];
in
python3Packages.buildPythonApplication {
    pname = "waypipe-desktop";
    version = "0.1.0";
    src = ../.;
    pyproject = true;

    build-system = [ python3Packages.setuptools ];
    makeWrapperArgs = [ "--prefix PATH : ${lib.makeBinPath runtimeInputs}" ];

    nativeCheckInputs = [ python3Packages.pytest ];
    checkPhase = ''
        runHook preCheck
        pytest
        runHook postCheck
    '';

    meta = {
        description = "Run Wayland applications from another host inside one shared session per host";
        homepage = "https://github.com/BeatLink/WaypipeDesktop";
        license = lib.licenses.gpl3Only;
        mainProgram = "waypipe-desktop";
        platforms = lib.platforms.linux;
    };
}
