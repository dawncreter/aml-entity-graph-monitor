from datetime import datetime, timedelta

import pytest

from amlgraph import monitor
from amlgraph.cli import main
from amlgraph.detectors import build_graph, find_cycles, find_pass_through, find_structuring
from amlgraph.models import Alert, Finding, Transaction
from amlgraph.sar import draft_sar
from amlgraph.scoring import anomaly_scores, naive_threshold_alerts, score_accounts
from amlgraph.synthetic import generate

T0 = datetime(2026, 1, 1, 9)


def tx(i, hours, s, r, amt, ch="wire"):
    return Transaction(f"X{i}", T0 + timedelta(hours=hours), s, r, amt, ch)


@pytest.fixture(scope="module")
def data():
    return generate(accounts=200)


# --- cycles ---------------------------------------------------------------------------
def test_detects_time_ordered_layering_cycle_starting_anywhere():
    txns = [tx(1, 0, "ACC1", "ACC2", 50_000), tx(2, 10, "ACC2", "ACC3", 49_000), tx(3, 20, "ACC3", "ACC1", 48_000)]
    (f,) = find_cycles(build_graph(txns))
    assert f.typology == "cycle" and f.accounts == ["ACC1", "ACC2", "ACC3"]
    assert f.detail.startswith("ACC1 -> ACC2")


def test_ignores_loops_that_are_out_of_order_or_too_slow_or_shrinking():
    out_of_order = [tx(1, 20, "A", "B", 50_000), tx(2, 10, "B", "C", 49_000), tx(3, 0, "C", "A", 48_000)]
    too_slow = [tx(1, 0, "A", "B", 50_000), tx(2, 10, "B", "C", 49_000), tx(3, 24 * 30, "C", "A", 48_000)]
    shrinking = [tx(1, 0, "A", "B", 50_000), tx(2, 10, "B", "C", 20_000), tx(3, 20, "C", "A", 19_000)]
    two_party = [tx(1, 0, "A", "B", 50_000), tx(2, 10, "B", "A", 49_000)]
    for txns in (out_of_order, too_slow, shrinking, two_party):
        assert find_cycles(build_graph(txns)) == []


# --- structuring --------------------------------------------------------------------
def test_structuring_needs_several_sub_threshold_cash_deposits():
    deps = [tx(i, i * 20, "CASH", "ACC9", 9_400, "cash") for i in range(4)]
    (f,) = find_structuring(deps)
    assert f.accounts == ["ACC9"] and len(f.txn_ids) == 4 and f.amount > 10_000
    assert find_structuring(deps[:2]) == []                                          # too few
    assert find_structuring([tx(9, 0, "CASH", "ACC9", 12_000, "cash")]) == []        # reported anyway
    spread = [tx(i, i * 24 * 10, "CASH", "ACC9", 9_400, "cash") for i in range(4)]  # 10 days apart
    assert find_structuring(spread) == []


# --- pass-through -------------------------------------------------------------------
def test_pass_through_requires_fast_near_full_onward_movement():
    mule = [tx(1, 0, "EXT", "ACC5", 20_000), tx(2, 3, "ACC5", "OFF", 19_000, "crypto"),
            tx(3, 100, "EXT", "ACC5", 30_000), tx(4, 105, "ACC5", "OFF", 29_000, "crypto")]
    (f,) = find_pass_through(mule)
    assert f.accounts == ["ACC5"] and len(f.txn_ids) == 4
    slow = [tx(1, 0, "EXT", "ACC5", 20_000), tx(2, 72, "ACC5", "OFF", 19_000),
            tx(3, 100, "EXT", "ACC5", 30_000), tx(4, 200, "ACC5", "OFF", 29_000)]
    assert find_pass_through(slow) == []
    assert find_pass_through(mule[:2]) == []  # one event is not a pattern


# --- scoring ------------------------------------------------------------------------------
def test_anomaly_scores_are_scaled_and_handle_tiny_inputs(data):
    txns, _ = data
    scores = anomaly_scores(txns)
    assert 0.0 <= min(scores.values()) and max(scores.values()) == pytest.approx(1.0)
    assert set(anomaly_scores(txns[:3]).values()) <= {0.0}


def test_rule_hits_dominate_score(data):
    txns, _ = data
    hit = Finding("cycle", ["ACC0010"], [], 1.0, "")
    alerts = score_accounts(txns, [hit], threshold=50)
    top = next(a for a in alerts if a.account == "ACC0010")
    assert top.score >= 60 and top.typologies == ["cycle"]
    assert all(a.score >= 50 for a in alerts)


def test_naive_baseline_only_counts_customer_accounts():
    txns = [tx(1, 0, "ACC1", "MER1", 9_500), tx(2, 0, "CASH", "ACC2", 9_500, "cash")]
    assert naive_threshold_alerts(txns) == {"ACC2"}


# --- end to end ---------------------------------------------------------------------------
def test_monitor_beats_threshold_baseline(data):
    txns, truth = data
    m = monitor(txns).metrics(truth)
    assert m["recall"] == 1.0 and m["precision"] >= 0.9
    assert m["precision"] > m["baseline_precision"]
    assert m["false_positives_removed_pct"] >= 80


def test_metrics_edge_cases():
    from amlgraph.pipeline import MonitorResult

    m = MonitorResult([], set()).metrics({})
    assert m["precision"] == 0.0 and m["recall"] == 1.0 and m["baseline_precision"] == 0.0


def test_sar_draft_contains_timeline_and_disclaimer(data):
    txns, _ = data
    alert = monitor(txns).alerts[0]
    sar = draft_sar(alert, txns)
    assert alert.account in sar and "| Date/time |" in sar and "Not a filing" in sar
    empty = draft_sar(Alert("ACC0001", 55.0), txns)
    assert "behavioural anomaly only" in empty and "n/a" in empty


def test_cli_demo(capsys):
    assert main(["demo", "--accounts", "120"]) == 0
    out = capsys.readouterr().out
    assert "DRAFT SAR" in out and "baseline_precision" in out
