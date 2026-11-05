"""Credit accounting for metered providers (Xpoz).

Xpoz has no endpoint that reports the credits left for an access key (``/api/plan`` and
``/api/usage`` need a dashboard session), so the only meter is the one we keep ourselves.

* :class:`CreditMeter` is the per-run budget (``XPOZ_RUN_CREDIT_BUDGET``). It refuses a call
  when its price does not fit in what is left, so a run stops at the exact credit, never one
  call past it.
* :class:`CreditLedger` is where spent credits are written for good. The Django side plugs a
  table or a shared cache in here later. It must never be process memory, because several
  workers share one provider account.

A key is recorded by its slot number (1, 2), never by its value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from ..errors import BudgetExceeded


@dataclass(frozen=True, slots=True)
class CreditEntry:
    provider: str
    route: str  # for example "x.users.search"
    credits: int
    key_slot: int  # 1 or 2, never the key itself
    at: datetime
    run_id: str | None = None


@runtime_checkable
class CreditLedger(Protocol):
    async def record(self, entry: CreditEntry) -> None:
        """Persist one spent charge."""
        ...


@runtime_checkable
class CappedLedger(CreditLedger, Protocol):
    """A ledger that also enforces a spending cap across runs and processes."""

    async def ensure_room(self, credits: int) -> None:
        """Raise ``BudgetExceeded`` when ``credits`` more would pass a daily cap."""
        ...


class CreditMeter:
    """Spend counter for one run. Not shared between runs."""

    def __init__(self, budget: int, *, provider: str) -> None:
        if budget < 0:
            raise ValueError("budget must not be negative")
        self.budget = budget
        self.provider = provider
        self.spent = 0

    @property
    def remaining(self) -> int:
        return self.budget - self.spent

    def can_afford(self, credits: int) -> bool:
        return credits <= self.remaining

    def charge(self, credits: int) -> None:
        """Reserve ``credits``. Raises ``BudgetExceeded`` and changes nothing when they do not fit."""
        if credits < 0:
            raise ValueError("credits must not be negative")
        if not self.can_afford(credits):
            raise BudgetExceeded(
                "run credit budget used up",
                provider=self.provider,
                spent=self.spent,
                budget=self.budget,
            )
        self.spent += credits
