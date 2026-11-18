"""Combine typology hits with an unsupervised anomaly score to rank accounts.

score = 100 * (1 - (1 - rule) * (1 - 0.3 * anomaly))
    rule    = 1 - prod(1 - w_t) over the distinct typologies hit (cycle 0.6, pass-through 0.55, structuring 0.5)
    anomaly = Isolation Forest outlier score scaled to [0, 1] over account behaviour features

Accounts below ``threshold`` are suppressed, which is where most false positives in
threshold-only monitoring are removed.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np
from sklearn.ensemble import IsolationForest

from .models import Alert, Finding, Transaction

WEIGHTS = {"cycle": 0.6, "pass_through": 0.55, "structuring": 0.5}
FEATURES = ["in_total", "out_total", "n_in", "n_out", "cash_share", "crypto_share", "counterparties", "flow_ratio"]


def account_features(txns: list[Transaction]) -> tuple[list[str], np.ndarray]:
    agg: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    peers: dict[str, set[str]] = defaultdict(set)
    for t in txns:
        r, s = agg[t.receiver], agg[t.sender]
        r["in_total"] += t.amount
        r["n_in"] += 1
        s["out_total"] += t.amount
        s["n_out"] += 1
        if t.channel == "cash":
            r["cash_in"] += t.amount
        if t.channel == "crypto":
            s["crypto_out"] += t.amount
        peers[t.receiver].add(t.sender)
        peers[t.sender].add(t.receiver)
    accounts = sorted(a for a in agg if a.startswith("ACC"))
    rows = []
    for a in accounts:
        f = agg[a]
        inn, out = f["in_total"], f["out_total"]
        rows.append([inn, out, f["n_in"], f["n_out"], f["cash_in"] / inn if inn else 0.0,
                     f["crypto_out"] / out if out else 0.0, len(peers[a]), out / inn if inn else 0.0])
    return accounts, np.log1p(np.array(rows, dtype=float))


def anomaly_scores(txns: list[Transaction], seed: int = 0) -> dict[str, float]:
    accounts, x = account_features(txns)
    if len(accounts) < 10:
        return dict.fromkeys(accounts, 0.0)
    raw = -IsolationForest(n_estimators=200, random_state=seed).fit(x).score_samples(x)
    lo, hi = raw.min(), raw.max()
    scaled = (raw - lo) / (hi - lo) if hi > lo else np.zeros_like(raw)
    return {a: float(s) for a, s in zip(accounts, scaled, strict=True)}


def score_accounts(txns: list[Transaction], findings: list[Finding], threshold: float = 50.0) -> list[Alert]:
    anomaly = anomaly_scores(txns)
    by_acct: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        for a in f.accounts:
            by_acct[a].append(f)
    alerts = []
    for acct in set(by_acct) | set(anomaly):
        hits = by_acct.get(acct, [])
        rule = 1 - float(np.prod([1 - WEIGHTS[t] for t in {f.typology for f in hits}]))
        an = anomaly.get(acct, 0.0)
        score = round(100 * (1 - (1 - rule) * (1 - 0.3 * an)), 1)
        if score >= threshold:
            alerts.append(Alert(acct, score, hits, round(an, 3)))
    return sorted(alerts, key=lambda a: a.score, reverse=True)


def naive_threshold_alerts(txns: list[Transaction], floor: float = 9_000) -> set[str]:
    """Baseline: flag every account that received any single transaction >= ``floor``."""
    return {t.receiver for t in txns if t.amount >= floor and t.receiver.startswith("ACC")}
