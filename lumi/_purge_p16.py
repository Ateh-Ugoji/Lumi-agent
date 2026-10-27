"""Purge the profile-16 latency-probe rows written by the PROMPT 5 smoke test.

Deletes ONLY profile 16's chat_messages + turn_classifications rows (the
"hi" probes). Nothing else in the DB is touched. Read-only elsewhere.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import delete

sys.stdout.reconfigure(encoding="utf-8")

from app.database import session_scope
from app.models.chat import ChatMessage
from app.models.turn_classification import TurnClassification


async def main() -> int:
    async with session_scope() as session:
        chat = await session.execute(
            delete(ChatMessage).where(ChatMessage.profile_id == 16).returning(ChatMessage.id)
        )
        chat_ids = list(chat.scalars())
        rows = await session.execute(
            delete(TurnClassification)
            .where(TurnClassification.profile_id == 16)
            .returning(TurnClassification.id)
        )
        tc_ids = list(rows.scalars())
        await session.commit()
    print(f"chat_messages deleted: {len(chat_ids)}")
    print(f"turn_classifications deleted: {len(tc_ids)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
