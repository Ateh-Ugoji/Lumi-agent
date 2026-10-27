"""Key probes: the hook LUMI-ARCHITECT's ``check_keys`` registers.

Usage from Django (``apps/intelligence/apps.py``)::

    from lumi_ai.keys import build_probes
    for probe in build_probes(ai_config):
        register(probe.name, probe.run, required=probe.required, env_vars=probe.env_vars)

Each probe makes one minimal real call (list models, then a one-token completion), reports the
provider's exact error on failure, warns when a configured model id is not in the provider's
catalog, and never raises. A missing optional key is ``skipped``, not an error. Probe results
never contain a key value.
"""

from __future__ import annotations

import httpx

from lumi_ai.config import AIConfig
from lumi_ai.ports import KeyProbe, ProbeResult
from lumi_ai.providers.urls import GROQ_BASE_URL, OPENLUX_BASE_URL, OPENROUTER_BASE_URL

PROBE_TIMEOUT_SECONDS = 20.0


def _redact(text: str, *secrets: str | None) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text[:300]


class _OpenAICompatProbe:
    """Lists models and (optionally) asks for one token from an OpenAI-compatible provider."""

    def __init__(
        self,
        *,
        name: str,
        required: bool,
        key_var: str,
        extra_vars: tuple[str, ...],
        base_url: str,
        api_key: str | None,
        models: tuple[str, ...],
        ping_model: str,
        ping_completion: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.name = name
        self.required = required
        self.env_vars = (key_var, *extra_vars)
        self._key_var = key_var
        self._base_url = base_url
        self._api_key = api_key
        self._models = models
        self._ping_model = ping_model
        self._ping = ping_completion
        self._transport = transport

    async def run(self) -> ProbeResult:
        if not self._api_key:
            level = "falta" if self.required else "OMITIDA (opcional, falta"
            detail = f"{level} {self._key_var}" + ("" if self.required else ")")
            return ProbeResult(
                self.name, "error" if self.required else "skipped", detail
            )
        headers = {"Authorization": f"Bearer {self._api_key}"}
        warnings: list[str] = []
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers=headers,
                timeout=PROBE_TIMEOUT_SECONDS,
                transport=self._transport,
            ) as http:
                listing = await http.get("/models")
                if listing.status_code != 200:
                    return self._http_error("GET /models", listing)
                available = {
                    m.get("id")
                    for m in listing.json().get("data", [])
                    if isinstance(m, dict)
                }
                for model in self._models:
                    if available and model not in available:
                        warnings.append(
                            f"modelo configurado '{model}' no existe en {self.name}"
                        )
                if self._ping:
                    reply = await http.post(
                        "/chat/completions",
                        json={
                            "model": self._ping_model,
                            "max_tokens": 1,
                            "messages": [{"role": "user", "content": "ping"}],
                        },
                    )
                    if reply.status_code != 200:
                        return self._http_error(
                            f"completion con {self._ping_model}", reply, tuple(warnings)
                        )
        except Exception as exc:  # noqa: BLE001 - a probe never raises
            return ProbeResult(
                self.name,
                "error",
                _redact(f"{type(exc).__name__}: {exc}", self._api_key),
                tuple(warnings),
            )
        detail = f"{len(available)} modelos" if available else "ok"
        return ProbeResult(self.name, "ok", detail, tuple(warnings))

    def _http_error(
        self, what: str, response: httpx.Response, warnings: tuple[str, ...] = ()
    ) -> ProbeResult:
        body = _redact(response.text, self._api_key)
        return ProbeResult(
            self.name, "error", f"{what}: HTTP {response.status_code} {body}", warnings
        )


class _OpenRouterProbe(_OpenAICompatProbe):
    """OpenRouter lists models without a key, so the key is checked on ``/auth/key`` first."""

    async def run(self) -> ProbeResult:
        if not self._api_key:
            return await super().run()
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=PROBE_TIMEOUT_SECONDS,
                transport=self._transport,
            ) as http:
                auth = await http.get("/auth/key")
            if auth.status_code != 200:
                return self._http_error("GET /auth/key", auth)
        except Exception as exc:  # noqa: BLE001
            return ProbeResult(
                self.name,
                "error",
                _redact(f"{type(exc).__name__}: {exc}", self._api_key),
            )
        return await super().run()


class _NeatlogsProbe:
    name = "neatlogs"
    required = False
    env_vars = ("NEATLOGS_API_KEY",)

    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key

    async def run(self) -> ProbeResult:
        if not self._api_key:
            return ProbeResult(
                self.name, "skipped", "OMITIDA (opcional, falta NEATLOGS_API_KEY)"
            )
        try:
            import neatlogs  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            return ProbeResult(
                self.name,
                "error",
                f"neatlogs no se puede importar: {type(exc).__name__}",
            )
        return ProbeResult(
            self.name,
            "ok",
            "key presente",
            (
                "la key no se valida contra el servidor: neatlogs no ofrece una llamada de comprobación",
            ),
        )


class _JevProbe:
    name = "jev"
    required = False
    env_vars = ("TYPESAFE_API_KEY",)

    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key

    async def run(self) -> ProbeResult:
        if not self._api_key:
            return ProbeResult(
                self.name, "skipped", "OMITIDA (opcional, falta TYPESAFE_API_KEY)"
            )
        try:
            from typesafe_sdk import AsyncTypeSafeClient, Noul

            client = AsyncTypeSafeClient(api_key=self._api_key)
            result = await client.system_one(
                state={"text": "ping"},
                questions={
                    "is_greeting": Noul(
                        instructions="Score 0..1: is the text a greeting?"
                    )
                },
            )
            if "is_greeting" not in result.answers:
                return ProbeResult(
                    self.name, "error", "Jev respondió sin la pregunta enviada"
                )
        except Exception as exc:  # noqa: BLE001
            return ProbeResult(
                self.name,
                "error",
                _redact(f"{type(exc).__name__}: {exc}", self._api_key),
            )
        return ProbeResult(self.name, "ok", "system_one respondió")


class _OptionalVarProbe:
    """Reports the video provider configuration without calling anything (T10 replaces it)."""

    name = "video"
    required = False
    env_vars = ("VIDEO_PROVIDER", "VIDEO_API_KEY")

    def __init__(self, provider: str | None, api_key: str | None) -> None:
        self._provider, self._api_key = provider, api_key

    async def run(self) -> ProbeResult:
        if not self._provider:
            return ProbeResult(
                self.name,
                "skipped",
                "OMITIDA (análisis de video apagado: falta VIDEO_PROVIDER)",
            )
        if not self._api_key:
            return ProbeResult(
                self.name,
                "error",
                f"VIDEO_PROVIDER={self._provider} pero falta VIDEO_API_KEY",
            )
        return ProbeResult(
            self.name,
            "skipped",
            "pendiente: la sonda real llega con el adaptador de video",
        )


def build_probes(
    config: AIConfig,
    *,
    ping_completion: bool = True,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[KeyProbe]:
    """Probes for every provider of the AI package, in the order ``check_keys`` should print them."""
    return [
        _OpenAICompatProbe(
            name="groq",
            required=True,
            key_var="GROQ_API_KEY",
            extra_vars=("GROQ_MODEL_LARGE", "GROQ_MODEL_SMALL", "GROQ_MODEL_FALLBACK"),
            base_url=GROQ_BASE_URL,
            api_key=config.groq_api_key,
            models=(
                config.groq_model_large,
                config.groq_model_small,
                config.groq_model_fallback,
                config.whisper_model,
            ),
            ping_model=config.groq_model_small,
            ping_completion=ping_completion,
            transport=transport,
        ),
        _OpenRouterProbe(
            name="openrouter",
            required=False,
            key_var="OPENROUTER_API_KEY",
            extra_vars=("OPENROUTER_MODEL",),
            base_url=OPENROUTER_BASE_URL,
            api_key=config.openrouter_api_key,
            models=(config.openrouter_model,),
            ping_model=config.openrouter_model,
            ping_completion=ping_completion,
            transport=transport,
        ),
        _OpenAICompatProbe(
            name="openlux",
            required=False,
            key_var="OPENLUX_API_KEY",
            extra_vars=("OPENLUX_MODEL",),
            base_url=OPENLUX_BASE_URL,
            api_key=config.openlux_api_key,
            models=(config.openlux_model,),
            ping_model=config.openlux_model,
            ping_completion=ping_completion,
            transport=transport,
        ),
        _JevProbe(config.typesafe_api_key),
        _NeatlogsProbe(config.neatlogs_api_key),
        _OptionalVarProbe(config.video_provider, config.video_api_key),
    ]
