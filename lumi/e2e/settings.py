"""Settings for the browser e2e server only (``e2e/server.py``).

Same as the test settings (no required keys, fast password hasher, eager Celery) plus the
local frontend origin. Provider calls never leave the process: ``e2e.sim`` swaps the provider
factories for ``httpx.MockTransport`` doubles.
"""

from config.settings.test import *

ROOT_URLCONF = "e2e.urls"
CORS_ALLOWED_ORIGINS = ["http://localhost:3010", "http://127.0.0.1:3010"]
