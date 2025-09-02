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
