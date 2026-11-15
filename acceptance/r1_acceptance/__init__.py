"""Dual-sandbox acceptance harness for requirement R1 of ``orbital`` (``orbital.bridges``).

The harness runs in the ChatGPT-side Docker Sandbox. It performs the acceptance procedure of
``plans/R1.md`` (section 16, steps D-1 ... D-9) through the ``orbital-bridge`` command line,
in stages that end at the manual checkpoints, and records every observation as immutable
evidence in a run directory. ``record`` adds the operator's observations of the Claude sandbox,
and ``report`` consolidates everything into a JSON and a Markdown report.

It never runs Docker or ``sbx`` commands, never changes network policies or published ports,
and never starts or stops the Claude-side bridge server; those steps are the operator's. It is
not part of the ``orbital`` package. Run it with::

    PYTHONPATH=<repository>/acceptance python3 -m r1_acceptance --help

The guide is ``acceptance/README.md``.
"""
