"""lumi_ai: the pure-Python AI package of Lumi.

Rules for everything under this package:

* It never imports Django (or any web framework). The Django glue lives in
  ``apps/intelligence``. A check in ``tests/test_boundaries.py`` enforces this.
* It talks to the rest of the system only through the ``typing.Protocol`` ports in
  :mod:`lumi_ai.ports`.
* No simulated responses in production code. Fakes live in ``tests/`` and ``fixtures/``.

Start reading at :mod:`lumi_ai.ports`.
"""
