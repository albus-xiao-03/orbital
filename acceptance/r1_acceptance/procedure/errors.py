"""Exceptions of the procedure."""

from __future__ import annotations


class StageRefusedError(Exception):
    """A stage cannot run now; the message says why and what to do instead.

    Nothing has been sent to the bridge when this is raised.
    """
