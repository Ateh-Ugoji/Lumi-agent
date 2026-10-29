"""Rebuild the vector index from PostgreSQL.

    python manage.py reindex_vectors [--collection voice_corpus|peer_posts|agent_memory]
                                     [--profile ID] [--no-reset]

PostgreSQL holds every text; Chroma holds only vectors, so the index can always be dropped and
rebuilt (after changing the embedder, or to clear vectors of deleted rows). Embedding is local
(ONNX MiniLM, free); the first run downloads the 79 MB model to ``~/.cache/chroma``.
Resetting a collection drops every profile's vectors in it, so ``--profile`` implies
``--no-reset``.
"""

from __future__ import annotations

import asyncio

from django.core.management.base import BaseCommand, CommandError

from apps.intelligence.reindex import run_reindex
from lumi_ai.config import AIConfig
from lumi_ai.rag.collections import COLLECTIONS
from lumi_ai.rag.errors import EmbedderUnavailable, VectorStoreError


class Command(BaseCommand):
    help = "Reconstruye los vectores de Chroma desde PostgreSQL."

    def add_arguments(self, parser):
        parser.add_argument(
            "--collection",
            action="append",
            choices=list(COLLECTIONS),
            dest="collections",
        )
        parser.add_argument("--profile", type=int, action="append", dest="profiles")
        parser.add_argument(
            "--no-reset",
            action="store_true",
            help="no borra la colección antes (deja vectores de filas ya borradas)",
        )

    def handle(self, *args, **options):
        reset = not options["no_reset"] and not options["profiles"]
        try:
            written = asyncio.run(
                run_reindex(
                    AIConfig.from_env(),
                    collections=options["collections"],
                    profile_ids=options["profiles"],
                    reset=reset,
                )
            )
        except (EmbedderUnavailable, VectorStoreError) as exc:
            raise CommandError(f"no se pudo reindexar: {exc}") from None
        for name, count in written.items():
            self.stdout.write(f"{name}: {count} vectores")
        self.stdout.write(
            f"listo ({'colecciones reiniciadas' if reset else 'sin reiniciar'})"
        )
