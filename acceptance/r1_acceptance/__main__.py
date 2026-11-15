"""Entry point: ``python -m r1_acceptance``."""

import sys

if sys.version_info < (3, 11):  # noqa: UP036 - a clear message on an older interpreter
    sys.exit("r1-acceptance needs Python 3.11 or newer")

from r1_acceptance.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
