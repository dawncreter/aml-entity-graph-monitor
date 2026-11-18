"""aml-monitor demo [--accounts N] [--sar ACCOUNT]"""
from __future__ import annotations

import argparse

from .pipeline import monitor
from .sar import draft_sar
from .synthetic import generate


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="aml-monitor")
    sub = ap.add_subparsers(dest="cmd", required=True)
    demo = sub.add_parser("demo")
    demo.add_argument("--accounts", type=int, default=300)
    demo.add_argument("--sar", help="print a draft SAR for this account (default: top alert)", default=None)
    args = ap.parse_args(argv)

    txns, truth = generate(accounts=args.accounts)
    result = monitor(txns)
    print(f"{len(txns):,} transactions · {args.accounts} accounts\n")
    print("| Account | Score | Typologies | Truth |\n|---|---|---|---|")
    for a in result.alerts:
        print(f"| {a.account} | {a.score} | {', '.join(a.typologies) or 'anomaly'} | {truth.get(a.account, '-')} |")
    print()
    for k, v in result.metrics(truth).items():
        print(f"  {k:<30} {v}")
    if result.alerts:
        target = next((a for a in result.alerts if a.account == args.sar), result.alerts[0])
        print("\n" + draft_sar(target, txns))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
