"""Command-line entry point. See plan.md §7."""

import argparse
import sys

from good_cop import __version__


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="good-cop")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    # live
    sub.add_parser("hook", help="Claude Code hook entry (reads JSON on stdin)")
    sub.add_parser("install", help="add good-cop hooks to ~/.claude/settings.json")
    sub.add_parser("uninstall", help="remove good-cop hooks from ~/.claude/settings.json")
    s = sub.add_parser("show", help="print ledger, summary and recent decisions")
    s.add_argument("session", nargs="?")
    s.add_argument("-n", type=int, default=10)
    s = sub.add_parser("summarise", help="bring summary.json up to date (worker)")
    s.add_argument("session")

    # backtest
    s = sub.add_parser("backtest", help="replay recorded sessions through the rules")
    s.add_argument("session", nargs="?")
    s.add_argument("--all", action="store_true")
    s.add_argument("--config")
    s.add_argument("--rules")
    s.add_argument("--with-summary", action="store_true")
    s = sub.add_parser("label", help="record a human label for a rule on a tool call")
    s.add_argument("session")
    s.add_argument("seq", type=int)
    s.add_argument("rule_id")
    s.add_argument("answer", choices=["yes", "no"])

    args = p.parse_args(argv)

    if args.cmd == "hook":
        from good_cop import hook
        return hook.main()
    if args.cmd in ("install", "uninstall"):
        from good_cop import install
        return getattr(install, args.cmd)()
    if args.cmd == "show":
        from good_cop import show
        return show.main(args.session, args.n)
    if args.cmd == "summarise":
        from good_cop import summary
        return summary.worker(args.session)
    if args.cmd == "backtest":
        from good_cop import backtest
        return backtest.main(args)
    if args.cmd == "label":
        from good_cop import backtest
        return backtest.label(args.session, args.seq, args.rule_id, args.answer == "yes")
    return 1


if __name__ == "__main__":
    sys.exit(main())
