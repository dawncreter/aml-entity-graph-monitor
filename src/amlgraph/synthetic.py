"""Synthetic transaction data with labelled money-laundering typologies.

Normal activity: payroll, rent, card-like merchant payments and occasional large legitimate
cash deposits. Injected typologies:
* layering cycle   – funds move A -> B -> C (-> D) -> A within days, losing a small fee per hop
* structuring      – repeated cash deposits just under the $10,000 reporting threshold
* pass-through     – an account receives funds and sends ~95% onward within hours
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from .models import Transaction

START = datetime(2026, 1, 5)


class _Gen:
    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.n = 0
        self.txns: list[Transaction] = []

    def add(self, t: datetime, s: str, r: str, amt: float, ch: str) -> None:
        self.n += 1
        self.txns.append(Transaction(f"T{self.n:06d}", t, s, r, round(amt, 2), ch))


def generate(accounts: int = 300, days: int = 60, seed: int = 11) -> tuple[list[Transaction], dict[str, str]]:
    """Return (transactions, {account: typology}) for the accounts that were really involved."""
    g = _Gen(seed)
    rng = g.rng
    accts = [f"ACC{i:04d}" for i in range(accounts)]
    employers = accts[:5]
    merchants = [f"MER{i:03d}" for i in range(40)]
    people = accts[5:]
    truth: dict[str, str] = {}

    for p in people:
        employer = rng.choice(employers)
        for d in range(0, days, 14):
            g.add(START + timedelta(days=d, hours=9), employer, p, rng.uniform(2500, 6000), "ach")
        for _ in range(rng.randint(8, 20)):
            g.add(START + timedelta(days=rng.uniform(0, days)), p, rng.choice(merchants), rng.uniform(5, 400), "card")
        if rng.random() < 0.05:  # legitimate one-off large cash deposit (e.g. car sale)
            g.add(START + timedelta(days=rng.uniform(0, days)), "CASH", p, rng.uniform(10000, 25000), "cash")

    pool = rng.sample(people, 24)
    # two layering cycles
    for ring in (pool[0:3], pool[3:7]):
        amt, t = rng.uniform(40000, 90000), START + timedelta(days=rng.uniform(5, 40))
        for a, b in zip(ring, ring[1:] + ring[:1], strict=True):
            t += timedelta(hours=rng.uniform(4, 30))
            g.add(t, a, b, amt, "wire")
            amt *= rng.uniform(0.96, 0.99)
            truth[a] = "cycle"
    # three structurers
    for p in pool[7:10]:
        t = START + timedelta(days=rng.uniform(5, 45))
        for _ in range(rng.randint(4, 6)):
            t += timedelta(hours=rng.uniform(6, 30))
            g.add(t, "CASH", p, rng.uniform(8800, 9900), "cash")
        truth[p] = "structuring"
    # two mules (pass-through)
    for p in pool[10:12]:
        for _ in range(3):
            t = START + timedelta(days=rng.uniform(5, 50))
            amt = rng.uniform(15000, 40000)
            g.add(t, f"EXT{rng.randint(0, 99):02d}", p, amt, "wire")
            g.add(t + timedelta(hours=rng.uniform(1, 12)), p, f"OFF{rng.randint(0, 9)}", amt * 0.95, "crypto")
        truth[p] = "pass_through"

    g.txns.sort(key=lambda x: x.time)
    return g.txns, truth
