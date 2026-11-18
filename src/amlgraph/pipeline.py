"""Run every detector, score accounts and compare against a threshold-only baseline."""
from __future__ import annotations

from dataclasses import dataclass

from .detectors import build_graph, find_cycles, find_pass_through, find_structuring
from .models import Alert, Transaction
from .scoring import naive_threshold_alerts, score_accounts


@dataclass
class MonitorResult:
    alerts: list[Alert]
    baseline: set[str]

    def metrics(self, truth: dict[str, str]) -> dict[str, float]:
        flagged = {a.account for a in self.alerts}
        bad = set(truth)
        tp, base_tp = len(flagged & bad), len(self.baseline & bad)
        return {
            "alerts": len(flagged),
            "precision": round(tp / len(flagged), 3) if flagged else 0.0,
            "recall": round(tp / len(bad), 3) if bad else 1.0,
            "baseline_alerts": len(self.baseline),
            "baseline_precision": round(base_tp / len(self.baseline), 3) if self.baseline else 0.0,
            "baseline_recall": round(base_tp / len(bad), 3) if bad else 1.0,
            "false_positives_removed_pct": round(
                100 * (1 - (len(flagged) - tp) / max(1, len(self.baseline) - base_tp)), 1),
        }


def monitor(txns: list[Transaction], threshold: float = 50.0) -> MonitorResult:
    g = build_graph(txns)
    findings = find_cycles(g) + find_structuring(txns) + find_pass_through(txns)
    return MonitorResult(score_accounts(txns, findings, threshold), naive_threshold_alerts(txns))
