{
  description = "ojaudit Python 开发与验证环境";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems
        (system: f system (import nixpkgs { inherit system; }));
    in {
      packages = forAllSystems (system: pkgs: {
        default = pkgs.python311Packages.buildPythonApplication {
          pname = "ojaudit";
          version = "0.1.0-dev0";
          pyproject = true;
          src = self;
          build-system = [ pkgs.python311Packages.hatchling ];
          dependencies = [ pkgs.python311Packages.tomli-w ];
          doCheck = false;
        };
      });
      apps = forAllSystems (system: pkgs: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/ojaudit";
        };
      });
      devShells = forAllSystems (system: pkgs: {
        default = pkgs.mkShell {
          packages = [
            pkgs.python311
            pkgs.python311Packages.pytest
            pkgs.python311Packages.tomli-w
            pkgs.ruff
            pkgs.uv
          ];
        };
      });
      checks = forAllSystems (system: pkgs: {
        default = pkgs.runCommand "ojaudit-check" {
          nativeBuildInputs = [
            pkgs.python311
            pkgs.python311Packages.pytest
            pkgs.python311Packages.tomli-w
            pkgs.ruff
          ];
        } ''
          export HOME="$TMPDIR/home"
          mkdir -p "$HOME"
          export RUFF_CACHE_DIR="$TMPDIR/ruff-cache"
          export PYTHONDONTWRITEBYTECODE=1
          export PYTEST_ADDOPTS="-p no:cacheprovider"
          export PYTHONPATH="${self}/src:${self}"
          cp -r ${self} ./source
          chmod -R u+w ./source
          cd ./source
          ruff check --no-cache .
          ruff format --check .
          python scripts/check_todos.py
          pytest -q
          touch $out
        '';
      });
    };
}
