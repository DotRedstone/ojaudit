{
  description = "ojaudit Python 开发与验证环境";
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f (import nixpkgs { inherit system; }));
    in {
      packages = forAllSystems (pkgs: {
        default = pkgs.python3Packages.buildPythonApplication {
          pname = "ojaudit";
          version = "0.1.0-dev0";
          pyproject = true;
          src = self;
          build-system = [ pkgs.python3Packages.hatchling ];
          doCheck = false;
        };
      });
      apps = forAllSystems (pkgs: { default = { type = "app"; program = "${self.packages.${pkgs.system}.default}/bin/ojaudit"; }; });
      devShells = forAllSystems (pkgs: { default = pkgs.mkShell { packages = [ pkgs.python3 pkgs.python3Packages.pytest pkgs.ruff pkgs.uv ]; }; });
      checks = forAllSystems (pkgs: { default = pkgs.runCommand "ojaudit-check" { nativeBuildInputs = [ pkgs.python3 pkgs.python3Packages.pytest pkgs.ruff ]; } ''
        cd ${self}
        export PYTHONPATH=$PWD/src:$PWD
        ruff check .
        python scripts/check_todos.py
        pytest -q
        touch $out
      ''; });
    };
}
