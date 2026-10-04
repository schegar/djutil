"""`python -m djutil_agent` entry point."""

import sys

from djutil_agent.cli import app

if __name__ == "__main__":
    sys.exit(app())
