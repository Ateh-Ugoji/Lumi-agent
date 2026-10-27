from unittest.mock import AsyncMock, patch

import pytest

from app.services.xpoz import XpozClient


@pytest.mark.asyncio
async def test_xpoz_client_get_user_live_posts():
    mock_payload = {
        "results": [
            {
                "id": "123456",
                "text": "Building agents that stay chronically online.",
                "likeCount": 150,
                "retweetCount": 25,
                "authorUsername": "sama",
            }
        ]
    }

    client = XpozClient()
    with patch.object(client._client, "get", new_callable=AsyncMock) as mock_get:
        class FakeResponse:
            def raise_for_status(self):
                pass
            def json(self):
                return mock_payload

        mock_get.return_value = FakeResponse()
        posts = await client.get_user_live_posts("sama", limit=5)
        assert len(posts) == 1
        assert posts[0]["id"] == "123456"
        assert posts[0]["likeCount"] == 150
        assert posts[0]["authorUsername"] == "sama"

    await client.aclose()
