"""Local, keyless embeddings behind the ``Embedder`` port.

Default: all-MiniLM-L6-v2 through ONNX (Chroma's own runtime). It needs no key and costs nothing;
the 79 MB model downloads once to ``~/.cache/chroma``. It is English-first: Spanish works but
ranks less sharply. Swap in another ``Embedder`` (the port is three members) if that matters.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from lumi_ai.rag.errors import EmbedderUnavailable

MODEL_NAME = "onnx-minilm-l6-v2"
DIMENSION = 384


class OnnxMiniLMEmbedder:
    def __init__(self) -> None:
        self._fn: Any = None

    @property
    def name(self) -> str:
        return MODEL_NAME

    @property
    def dimension(self) -> int:
        return DIMENSION

    def _load(self) -> Any:
        if self._fn is None:
            try:
                from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

                self._fn = ONNXMiniLM_L6_V2()
            except Exception as exc:  # download blocked, no disk, onnxruntime missing
                raise EmbedderUnavailable(
                    f"embedding model could not load: {exc}"
                ) from exc
        return self._fn

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        fn = self._load()
        try:
            return [[float(x) for x in vec] for vec in fn(list(texts))]
        except Exception as exc:
            raise EmbedderUnavailable(f"embedding failed: {exc}") from exc
