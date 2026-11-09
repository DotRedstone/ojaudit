"""
Module: CLI Entry
Description: 提供开发阶段的命令行入口。
Scope: CLI
"""

import argparse


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ojaudit", description="训练赛代码审查框架")
    parser.parse_args(argv)
    print("ojaudit 尚处于仓库骨架阶段；功能将在后续 PR 实现。")


if __name__ == "__main__":
    main()
