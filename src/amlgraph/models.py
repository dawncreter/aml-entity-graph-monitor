"""Core records."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class Transaction:
    txn_id: str
    time: datetime
    sender: str
    receiver: str
    amount: float
    channel: str  # wire | ach | cash | crypto


@dataclass
class Finding:
    """One typology hit on one or more accounts."""

    typology: str  # cycle | structuring | pass_through
    accounts: list[str]
    txn_ids: list[str]
    amount: float
    detail: str


@dataclass
class Alert:
    account: str
    score: float
    findings: list[Finding] = field(default_factory=list)
    anomaly: float = 0.0

    @property
    def typologies(self) -> list[str]:
        return sorted({f.typology for f in self.findings})
