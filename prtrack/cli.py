from __future__ import annotations

import subprocess
import sys
from typing import NoReturn

from . import __version__
from .tui import PRTrackApp


def main() -> None:
    """Entry point for the `prtrack` console script.

    Launches the Textual TUI application or handles CLI commands.

    Returns:
        None
    """
    # Check if any command-line arguments were provided
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "update":
            update_tool()
            return
        elif command in ("--version", "-v"):
            print(f"prtrack {__version__}")
            return
        elif command in ("--help", "-h"):
            print_help()
            return

    # Default behavior: launch the TUI
    PRTrackApp().run()


def update_tool() -> NoReturn:
    """Update the prtrack tool using uv tool upgrade.

    This function executes the uv tool upgrade command to update
    the prtrack tool to the latest version.

    Returns:
        NoReturn: Exits the program with the return code from the uv command.
    """
    try:
        # Run uv tool upgrade for prtrack
        result = subprocess.run(["uv", "tool", "upgrade", "prtrack"], check=False)
        sys.exit(result.returncode)
    except FileNotFoundError:
        # uv is not installed
        print("Error: uv is not installed or not found in PATH.", file=sys.stderr)
        print("Please install uv from https://docs.astral.sh/uv/", file=sys.stderr)
        sys.exit(1)


def print_help() -> None:
    """Print help message for prtrack CLI commands.

    Returns:
        None
    """
    help_text = """prtrack - Terminal-based GitHub PR tracker

Usage:
  prtrack              Launch the TUI application
  prtrack update       Update the prtrack tool
  prtrack --version    Show version information
  prtrack --help       Show this help message

Commands:
  update               Update the prtrack tool using uv

Options:
  -h, --help           Show this help message
  -v, --version        Show version information

For more information, visit: https://github.com/RavindraGDP/prtrack
"""
    print(help_text)
