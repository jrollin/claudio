import argparse
import sys

import state
import weekly_features
import weekly_state
import weekly_window


def run_init(args):
    weekly_state.write(args.out, weekly_state.initial_state(args.digest))
    return 0


def run_window(args):
    zone = state.load_zone(args.tz)
    now = weekly_window.load_now(args.now)
    weekly_state.load(args.state)
    window = weekly_window.compute_window(now, zone, args.report_only)
    state.write_all([(args.out, state.dump(window))])
    return 0


COMMANDS = {"init": run_init, "window": run_window, "features": weekly_features.run_features}


def build_parser():
    parser = argparse.ArgumentParser(prog="weekly.py", description="Weekly status engine")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="write the empty state of a weekly routine that has none")
    for flag in ("--digest", "--out"):
        init.add_argument(flag, required=True)
    window = commands.add_parser("window", help="compute the week of --now, from Monday 00:00 in --tz")
    for flag in ("--state", "--now", "--tz", "--out"):
        window.add_argument(flag, required=True)
    window.add_argument("--report-only", action="store_true", help="marks the window, which keeps no cursor and so changes nothing else")
    features = commands.add_parser("features", help="write the items of the week and the sources read; decides nothing")
    for flag in ("--config", "--routine", "--window", "--collections", "--out"):
        features.add_argument(flag, required=True)
    features.add_argument("--recap", help="folder holding the recap routine's state.json and its runs/ records")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except state.InputError as error:
        print(f"weekly.py: {error}", file=sys.stderr)
        return 2
    except state.Rejected as error:
        print(f"weekly.py: rejected: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
