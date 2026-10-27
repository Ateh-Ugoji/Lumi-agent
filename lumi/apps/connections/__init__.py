"""Social connections: OAuth providers, token encryption and API clients.

The core modules do not import Django. Persistence sits behind small Protocols
(``oauth.OAuthStateStore``, ``publishing.PublishLedger``) so the Django models owned by
LUMI-ARCHITECT plug in later without changing the logic here.
"""
