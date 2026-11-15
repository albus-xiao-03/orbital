import sys

if sys.version_info < (3, 11):  # noqa: UP036 - a clear message on an older interpreter
    sys.exit("r1-retest needs Python 3.11 or newer")

from r1_retest.cli.main import main

if __name__ == "__main__":
    sys.exit(main())
