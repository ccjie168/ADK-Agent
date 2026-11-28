#!/usr/bin/env python3
"""Run the import-linter contract and the ADK import wall (ADR-0046)."""

import sys

from importlinter.cli import lint_imports_command

import adk_wall


def main() -> None:
    if adk_wall.main() != 0:
        raise SystemExit(1)
    lint_imports_command.main(args=["--no-cache"])


if __name__ == "__main__":
    sys.exit(main())
