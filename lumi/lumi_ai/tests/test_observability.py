from lumi_ai import observability
from lumi_ai.config import AIConfig


def test_everything_is_a_no_op_without_a_key():
    assert observability.init_tracing(AIConfig()) is False
    client = object()
    assert observability.wrap_client(client, "groq") is client
    with observability.span("x"):
        pass
    observability.log_event("hello", a=1)
    observability.flush_and_shutdown()
