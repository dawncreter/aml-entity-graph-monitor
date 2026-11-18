"""Draft a Suspicious Activity Report (SAR) narrative for investigator review.

The output is a starting draft. An investigator reviews, edits and decides whether to file.
"""
from __future__ import annotations

from .models import Alert, Transaction

LABELS = {
    "cycle": "circular movement of funds consistent with layering",
    "structuring": "cash deposits structured below the $10,000 reporting threshold",
    "pass_through": "rapid pass-through of funds consistent with a money-mule account",
}


def draft_sar(alert: Alert, txns: list[Transaction]) -> str:
    ids = {i for f in alert.findings for i in f.txn_ids}
    timeline = sorted((t for t in txns if t.txn_id in ids), key=lambda t: t.time)
    total = sum(t.amount for t in timeline)
    first = timeline[0].time.date() if timeline else "n/a"
    last = timeline[-1].time.date() if timeline else "n/a"
    lines = [
        f"# DRAFT SAR narrative — subject account {alert.account}",
        "",
        f"**Risk score:** {alert.score}/100 · **Anomaly:** {alert.anomaly:.2f} · "
        f"**Typologies:** {', '.join(alert.typologies) or 'behavioural anomaly only'}",
        "",
        "## Summary",
        (f"Between {first} and {last}, account {alert.account} was involved in {len(timeline)} transactions "
         f"totalling ${total:,.2f} that show "
         + ("; ".join(LABELS[t] for t in alert.typologies) or "unusual behaviour relative to peers") + "."),
        "",
        "## Findings",
        *[f"- **{f.typology}:** {f.detail}" for f in alert.findings],
        "",
        "## Transaction timeline",
        "| Date/time | ID | From | To | Amount | Channel |",
        "|---|---|---|---|---|---|",
        *[f"| {t.time:%Y-%m-%d %H:%M} | {t.txn_id} | {t.sender} | {t.receiver} | ${t.amount:,.2f} | {t.channel} |"
          for t in timeline],
        "",
        "_Draft generated for investigator review. Not a filing._",
    ]
    return "\n".join(lines)
