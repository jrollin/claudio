import argparse
import sys

import recap_state
import recap_window
import state

STUBS = ("seed", "features", "judge", "apply", "message")


def lookback_days(text):
    try:
        value = int(text)
    except ValueError:
        value = 0
    if not 1 <= value <= recap_window.MAX_LOOKBACK_WORKING_DAYS:
        raise argparse.ArgumentTypeError(f"expected an integer from 1 to {recap_window.MAX_LOOKBACK_WORKING_DAYS}, got {text}")
    return value


def run_init(args):
    recap_state.write(args.out, recap_state.initial_state(args.digest))
    return 0


def run_window(args):
    zone = state.load_zone(args.tz)
    now = state.load_time(args.now, "--now")
    since = None if args.since is None else state.load_time(args.since, "--since")
    document = recap_state.load(args.state)
    window = recap_window.compute_window(document, now, zone, args.lookback_working_days, since, args.report_only)
    state.write_all([(args.out, state.dump(window))])
    return 0


def run_stub(args):
    raise state.InputError(f"{args.command}: not implemented yet")


COMMANDS = {"init": run_init, "window": run_window, **{name: run_stub for name in STUBS}}


def build_parser():
    parser = argparse.ArgumentParser(prog="recap.py", description="Chat recap engine")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="write the baseline state of a recap routine that has none")
    for flag in ("--digest", "--out"):
        init.add_argument(flag, required=True)
    window = commands.add_parser("window", help="compute the run window from the recap state")
    for flag in ("--state", "--now", "--tz", "--out"):
        window.add_argument(flag, required=True)
    window.add_argument("--lookback-working-days", type=lookback_days, required=True, help="working days read by a baseline run or after a longer gap")
    start = window.add_mutually_exclusive_group()
    start.add_argument("--since", help="explicit window start, uncapped; the run then never advances the state")
    start.add_argument("--report-only", action="store_true", help="normal window start, marked explicit so the run never advances the state")
    for name in STUBS:
        commands.add_parser(name, help="not implemented yet").add_argument("rest", nargs=argparse.REMAINDER)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except state.InputError as error:
        print(f"recap.py: {error}", file=sys.stderr)
        return 2
    except state.Rejected as error:
        print(f"recap.py: rejected: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
