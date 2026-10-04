"""PyInstaller entry point for the windowed 'DJUtil Agent' build.

Started without arguments it launches the tray; arguments are passed
through to the regular CLI.
"""

import sys

from djutil_agent.cli import app

if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv.append("tray")
    app()
