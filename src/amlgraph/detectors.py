"""Typology detectors over a transaction graph."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

import networkx as nx

from .models import Finding, Transaction

REPORTING_THRESHOLD = 10_000.0


def build_graph(txns: list[Transaction]) -> nx.MultiDiGraph:
    """Accounts are nodes; every transaction is a timestamped, amount-weighted edge."""
    g = nx.MultiDiGraph()
    for t in txns:
        g.add_edge(t.sender, t.receiver, key=t.txn_id, time=t.time, amount=t.amount, channel=t.channel)
    return g


def find_cycles(g: nx.MultiDiGraph, max_len: int = 5, window: timedelta = timedelta(days=10),
                min_amount: float = 10_000, min_retained: float = 0.8) -> list[Finding]:
    """Closed loops A -> B -> ... -> A where each hop happens after the previous one, inside ``window``,
    and keeps at least ``min_retained`` of the previous hop's amount (layering, not coincidence)."""
    simple = nx.DiGraph()
    for u, v, d in g.edges(data=True):
        if d["amount"] >= min_amount and u != v:
            simple.add_edge(u, v)
    findings: list[Finding] = []
    for cycle in nx.simple_cycles(simple, length_bound=max_len):
        if len(cycle) < 3:
            continue
        for r in range(len(cycle)):  # the loop can start at any member, so try every rotation
            ring = cycle[r:] + cycle[:r]
            hit = _time_ordered_path(g, ring, window, min_amount, min_retained)
            if hit:
                findings.append(Finding("cycle", sorted(ring), [e[0] for e in hit], hit[0][1],
                                        " -> ".join([*ring, ring[0]])))
                break
    return findings


def _time_ordered_path(g: nx.MultiDiGraph, cycle: list[str], window: timedelta, min_amount: float,
                       min_retained: float) -> list[tuple[str, float]] | None:
    """Greedy search for one time-ordered chain of edges around the cycle."""
    hops = list(zip(cycle, cycle[1:] + cycle[:1], strict=True))
    first_edges = sorted(((k, d) for k, d in g[hops[0][0]][hops[0][1]].items() if d["amount"] >= min_amount),
                         key=lambda kd: kd[1]["time"])
    for k0, d0 in first_edges:
        path, last_t, last_amt = [(k0, d0["amount"])], d0["time"], d0["amount"]
        for u, v in hops[1:]:
            nxt = [(k, d) for k, d in g[u][v].items()
                   if last_t < d["time"] <= d0["time"] + window and d["amount"] >= last_amt * min_retained]
            if not nxt:
                break
            k, d = min(nxt, key=lambda kd: kd[1]["time"])
            path.append((k, d["amount"]))
            last_t, last_amt = d["time"], d["amount"]
        else:
            return path
    return None


def find_structuring(txns: list[Transaction], low: float = 8_000, window: timedelta = timedelta(days=7),
                     min_count: int = 3) -> list[Finding]:
    """Several cash deposits just under the reporting threshold that together exceed it."""
    by_acct: dict[str, list[Transaction]] = defaultdict(list)
    for t in txns:
        if t.channel == "cash" and low <= t.amount < REPORTING_THRESHOLD:
            by_acct[t.receiver].append(t)
    findings = []
    for acct, deps in by_acct.items():
        deps.sort(key=lambda t: t.time)
        best: list[Transaction] = []
        for i in range(len(deps)):
            win = [d for d in deps[i:] if d.time - deps[i].time <= window]
            if len(win) > len(best):
                best = win
        total = sum(d.amount for d in best)
        if len(best) >= min_count and total > REPORTING_THRESHOLD:
            findings.append(Finding("structuring", [acct], [d.txn_id for d in best], total,
                                    f"{len(best)} cash deposits of ${low:,.0f}-${REPORTING_THRESHOLD:,.0f} "
                                    f"within {window.days} days (total ${total:,.0f})"))
    return findings


def find_pass_through(txns: list[Transaction], max_hold: timedelta = timedelta(hours=24), min_ratio: float = 0.9,
                      min_amount: float = 10_000, min_events: int = 2) -> list[Finding]:
    """Funds that arrive and leave again (>= ``min_ratio``) within ``max_hold``, repeatedly."""
    inbound: dict[str, list[Transaction]] = defaultdict(list)
    outbound: dict[str, list[Transaction]] = defaultdict(list)
    for t in txns:
        if t.amount >= min_amount * min_ratio:
            inbound[t.receiver].append(t)
            outbound[t.sender].append(t)
    findings = []
    for acct, ins in inbound.items():
        used: set[str] = set()
        pairs: list[tuple[Transaction, Transaction]] = []
        for i in sorted(ins, key=lambda t: t.time):
            if i.amount < min_amount:
                continue
            for o in sorted(outbound.get(acct, []), key=lambda t: t.time):
                if o.txn_id not in used and timedelta(0) < o.time - i.time <= max_hold \
                        and min_ratio <= o.amount / i.amount <= 1.0:
                    pairs.append((i, o))
                    used.add(o.txn_id)
                    break
        if len(pairs) >= min_events:
            moved = sum(o.amount for _, o in pairs)
            findings.append(Finding("pass_through", [acct], [t.txn_id for p in pairs for t in p], moved,
                                    f"{len(pairs)} in/out pairs within {max_hold.total_seconds() / 3600:.0f}h, "
                                    f"${moved:,.0f} moved onward"))
    return findings
