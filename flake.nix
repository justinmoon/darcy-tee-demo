{
  description = "Darcy confidential Tau demo";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/5adc50831c259f87faeb09ddf930d43597197473";
  inputs.tau = { url = "github:dpc/tau/aeeaf2b77f44019c9a982766fe35417f98cf92e0"; flake = false; };
  outputs = { self, nixpkgs, tau }: let
    buildTau = pkgs: pkgs.rustPlatform.buildRustPackage {
      pname = "darcy-tau"; version = "0.2.1-dev";
      src = tau; cargoLock.lockFile = "${tau}/Cargo.lock";
      patches = [ ./nix/tau-container.patch ];
      cargoBuildType = "debug";
      env.RUSTFLAGS = "-C debuginfo=0";
      cargoBuildFlags = [ "--package" "dpc-tau" ]; doCheck = false;
    };
    linux = import nixpkgs { system = "x86_64-linux"; };
    mac = import nixpkgs { system = "aarch64-darwin"; };
    python = p: p.python3.withPackages (q: [ q.cbor2 q.cryptography q.pyyaml ]);
    cli = linux.stdenvNoCC.mkDerivation {
      pname = "tinfoil-cli"; version = "0.19.9";
      src = linux.fetchurl {
        url = "https://github.com/tinfoilsh/tinfoil-cli/releases/download/v0.19.9/tinfoil-cli_0.19.9_linux_amd64.tar.gz";
        hash = "sha256-bJu6+OfcTPFQLPoiLPi631M4YVfdi0M6woVcRlC6u3c=";
      };
      sourceRoot = "."; installPhase = "mkdir -p $out/bin; cp tinfoil $out/bin/";
    };
    env = linux.buildEnv { name = "darcy-tee-env";
      paths = [ (buildTau linux) (python linux) cli linux.bashInteractive linux.coreutils linux.curl linux.git linux.gnugrep linux.gnused linux.findutils linux.gawk linux.util-linuxMinimal linux.openssh linux.gnutar linux.gzip linux.cacert ];
      pathsToLink = [ "/bin" "/etc" ];
    };
    app = linux.runCommand "darcy-tee-app" {} ''
      mkdir -p $out/app
      cp -r ${./app}/* $out/app/
    '';
  in {
    devShells.aarch64-darwin.default = mac.mkShell { packages = [ (python mac) mac.just mac.skopeo mac.ruff ]; };
    packages.aarch64-darwin = {
      image = mac.dockerTools.buildLayeredImage {
        name = "ghcr.io/justinmoon/darcy-tee-demo"; tag = "dev";
        architecture = "amd64";
        contents = [ env app ]; maxLayers = 25;
        extraCommands = ''
          mkdir -p tmp workspace etc
          chmod 1777 tmp
          printf 'root:x:0:0:root:/workspace:/bin/bash\nagent:x:1000:1000:Agent:/workspace:/bin/bash\n' > etc/passwd
          printf 'root:x:0:\nagent:x:1000:\n' > etc/group
        '';
        config = {
          Cmd = [ "${python linux}/bin/python3" "/app/server.py" ];
          User = "1000:1000"; WorkingDir = "/workspace";
          Env = [ "PATH=/bin" "HOME=/workspace" "SSL_CERT_FILE=${linux.cacert}/etc/ssl/certs/ca-bundle.crt" "PYTHONDONTWRITEBYTECODE=1" "PYTHONUNBUFFERED=1" ];
          ExposedPorts."8080/tcp" = {};
          Labels."org.opencontainers.image.source" = "https://github.com/justinmoon/darcy-tee-demo";
        };
      };
    };
  };
}
