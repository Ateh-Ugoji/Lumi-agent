"""Social connections: OAuth providers, API clients and the Django tables behind them.

The core modules do not import Django. Persistence sits behind small Protocols
(``oauth.OAuthStateStore``, ``publishing.PublishLedger``, ``handles.types.HandleStore``,
``clients.credits.CreditLedger``). ``models.py`` and ``stores.py`` are the Django side.
Tokens are encrypted by ``apps.core.fields.EncryptedTextField``.
"""
