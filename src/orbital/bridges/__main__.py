"""Entry point of ``python -m orbital.bridges``: the ``orbital-bridge`` command line."""

import sys

from orbital.bridges.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
