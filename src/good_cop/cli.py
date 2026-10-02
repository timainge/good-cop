"""Command-line entry point. See plan.md §7."""

import argparse
import sys

from good_cop import __version__


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="good-cop")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    # live
    s = sub.add_parser("hook", help="hook entry (reads JSON on stdin)")
    s.add_argument("--harness", choices=["claude", "codex", "cursor", "copilot"], default="claude")
    s.add_argument("--event", help="event name, for harnesses whose payload doesn't carry it")
    for name, verb in (("install", "add good-cop hooks to"), ("uninstall", "remove good-cop hooks from")):
        s = sub.add_parser(name, help=f"{verb} the harness's hook config (default ~/.claude/settings.json)")
        s.add_argument("--settings", help="config file to edit instead")
        s.add_argument("--harness", choices=["claude", "codex", "cursor", "copilot"], default="claude")
        if name == "install":
            s.add_argument("--ruleset", action="append", default=[],
                           help="add a starter ruleset to ~/.good-cop/rules.yaml's include list (repeatable)")
    s = sub.add_parser("rules", help="list starter rulesets, or show the effective merged rules")
    rs = s.add_subparsers(dest="rules_cmd", required=True)
    rs.add_parser("list", help="bundled starter rulesets")
    r = rs.add_parser("show", help="print the effective rules after includes and overrides")
    r.add_argument("--ruleset", help="a bundled ruleset on its own")
    r.add_argument("--rules", help="rules file (default ~/.good-cop/rules.yaml)")
    s = sub.add_parser("show", help="print ledger, summary and recent decisions")
    s.add_argument("session", nargs="?")
    s.add_argument("-n", type=int, default=10)
    s = sub.add_parser("summarise", help="bring summary.json up to date (worker)")
    s.add_argument("session")

    # backtest
    s = sub.add_parser("backtest", help="replay recorded sessions through the rules")
    s.add_argument("sessions", nargs="*", help="session ids or prefixes (default: latest)")
    s.add_argument("--all", action="store_true")
    s.add_argument("--config", action="append", help="config file; repeat to compare two")
    s.add_argument("--rules")
    s.add_argument("--with-summary", action="store_true")
    s.add_argument("--limit", type=int, help="max tool calls per session")
    s.add_argument("--workers", type=int, default=4)
    s.add_argument("--note", help="free-text label saved with the run summary")
    sub.add_parser("evals", help="list saved backtest runs and their metrics")
    s = sub.add_parser("handler", help="run a named on_trip handler (event JSON on stdin)")
    s.add_argument("name")
    s.add_argument("--test", action="store_true", help="send a sample event instead of reading stdin")
    s.add_argument("--rules")
    s = sub.add_parser("label", help="record a human label for a rule on a tool call")
    s.add_argument("session")
    s.add_argument("seq", type=int)
    s.add_argument("rule_id")
    s.add_argument("answer", choices=["yes", "no"])
    s = sub.add_parser("review", help="label tool calls interactively: tripped, near-misses, a sample of negatives")
    s.add_argument("sessions", nargs="*", help="session ids or prefixes (default: sessions active in the last 7d)")
    s.add_argument("--since", help="sessions with events in this window, e.g. 7d, 12h")
    s.add_argument("--rule", help="only this rule id")
    s.add_argument("--from-backtest", metavar="RUN", help="take probabilities from a saved backtest run (id or 'latest')")
    s.add_argument("--rules", help="rules file (default: the run's rules, else ~/.good-cop/rules.yaml)")
    s.add_argument("--negatives", type=int, default=10, help="clear negatives to sample (default 10)")
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--labeller", help="name saved with each label (default: $USER)")
    s = sub.add_parser("import", help="import Claude Code transcripts as sessions (test data)")
    s.add_argument("paths", nargs="*")
    s.add_argument("--all", action="store_true", help="every transcript in ~/.claude/projects")
    s.add_argument("--project", help="transcripts whose project dir contains this string")
    s.add_argument("--force", action="store_true")

    args = p.parse_args(argv)

    if args.cmd == "hook":
        from good_cop import hook
        return hook.main(args.harness, args.event)
    if args.cmd in ("install", "uninstall"):
        from good_cop import install
        if args.cmd == "install":
            return install.install(args.settings, args.harness, args.ruleset)
        return install.uninstall(args.settings, args.harness)
    if args.cmd == "rules":
        from good_cop import install
        return install.rules_cmd(args)
    if args.cmd == "show":
        from good_cop import show
        return show.main(args.session, args.n)
    if args.cmd == "summarise":
        from good_cop import summary
        return summary.worker(args.session)
    if args.cmd == "backtest":
        from good_cop import backtest
        return backtest.main(args)
    if args.cmd == "handler":
        import json
        from good_cop import config, handlers
        payload = handlers.SAMPLE if args.test else json.load(sys.stdin)
        code = handlers.run(args.name, payload, config.load_rules(args.rules))
        if args.test:
            print(f"handler {args.name!r} exited {code}" + ("" if code == 0 else "; see ~/.good-cop/errors.log"))
        return code
    if args.cmd == "evals":
        from good_cop import backtest
        return backtest.evals()
    if args.cmd == "label":
        from good_cop import backtest
        return backtest.label(args.session, args.seq, args.rule_id, args.answer == "yes")
    if args.cmd == "review":
        from good_cop import review
        return review.main(args)
    if args.cmd == "import":
        from good_cop import transcripts
        return transcripts.main(args.paths, args.all, args.project, args.force)
    return 1


if __name__ == "__main__":
    sys.exit(main())
