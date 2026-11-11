#!/usr/bin/env python3
"""Run the import-linter layering contract."""

from importlinter.cli import lint_imports_command

if __name__ == "__main__":
    lint_imports_command.main(args=["--no-cache"])
