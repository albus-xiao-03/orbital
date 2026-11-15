"""r1-retest: the semi-automated harness for the targeted R1 dual-sandbox re-test.

It runs in the ChatGPT-side sandbox, drives the Claude-side bridge only through the
`orbital.bridges` command line, and records every result as immutable evidence. It lives in
acceptance/, outside the `orbital` package, and uses only the Python standard library.
The operator guide is GUIDE.md next to this file (also printed by ``r1-retest guide``).
"""
