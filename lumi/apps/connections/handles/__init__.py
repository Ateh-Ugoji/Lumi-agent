"""Handle search (the ``@`` autocomplete): cache first, credit aware, never locked to the cache.

The logic here is pure Python. Storage is a ``HandleStore`` and the paid lookup is a
``HandleLive``; the Django models and the Xpoz adapter plug into those two seams.
"""
