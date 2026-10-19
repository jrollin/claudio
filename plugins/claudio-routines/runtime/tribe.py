import argparse
import sys

import roles
import state
import tribe_features
import tribe_lifecycle
import tribe_message
import tribe_publish
import tribe_seed
import tribe_state


def window_clock(document):
    return {"run": {"at": document["run"]["at"]}}


def run_init(args):
    tribe_state.write(args.out, tribe_state.initial_state(args.digest))
    return 0


def run_window(args):
    zone = state.load_zone(args.tz)
    now = state.load_time(args.now, "--now")
    since = None if args.since is None else state.load_time(args.since, "--since")
    document = tribe_state.load(args.state)
    window = state.compute_window(window_clock(document), now, zone, since, args.report_only)
    state.write_all([(args.out, state.dump(window))])
    return 0


def run_seed(args):
    tribe_state.write(args.out, tribe_seed.seed(args.page, args.config, args.routine))
    return 0


def run_judge(args):
    tribe_lifecycle.judge(args.features, args.judgment)
    return 0


def run_apply(args):
    applied = tribe_lifecycle.apply(args.state, args.features, args.base, args.judgment, args.window)
    next_state = applied.raw if applied.raw is not None else state.dump(applied.state)
    state.write_all([(args.out, next_state), (args.record, state.dump(applied.record)), (args.summary, state.dump(applied.summary))])
    return 0


COMMANDS = {
    "init": run_init,
    "window": run_window,
    "seed": run_seed,
    "features": tribe_features.run_features,
    "judge": run_judge,
    "apply": run_apply,
    "render": tribe_publish.run_render,
    "publish-plan": tribe_publish.run_publish_plan,
    "publish-parse": tribe_publish.run_publish_parse,
    "message": tribe_message.run_message,
}


def add_publish_parsers(commands):
    routine_flags = ("--config", "--routine", "--summary")
    render = commands.add_parser("render", help="render the digest page from the summary and run the structure check; exits 3 when it fails")
    for flag in (*routine_flags, "--out"):
        render.add_argument(flag, required=True)
    render.add_argument("--place", required=True, choices=roles.PLACES)
    plan = commands.add_parser("publish-plan", help="write the next connector call that creates the page and its weekly heading")
    for flag in (*routine_flags, "--state", "--page", "--responses", "--out"):
        plan.add_argument(flag, required=True)
    plan.add_argument("--place", required=True, choices=roles.PLACES)
    parse = commands.add_parser("publish-parse", help="read the saved connector results into the published state and the result file")
    for flag in (*routine_flags, "--state", "--responses", "--now", "--out", "--result"):
        parse.add_argument(flag, required=True)
    parse.add_argument("--place", required=True, choices=roles.PLACES)
    message = commands.add_parser("message", help="render the chat message, or a one-line degraded message")
    message.add_argument("--out", required=True)
    message.add_argument("--degraded", choices=tribe_message.CAUSES, help="cause of a run that wrote no page")
    for flag in ("--summary", "--result", "--config", "--routine"):
        message.add_argument(flag)
    message.add_argument("--place", choices=roles.PLACES)


def build_parser():
    parser = argparse.ArgumentParser(prog="tribe.py", description="Tribe digest engine")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="write the baseline state of a tribe routine that has none")
    for flag in ("--digest", "--out"):
        init.add_argument(flag, required=True)
    window = commands.add_parser("window", help="compute the run window from the tribe state")
    for flag in ("--state", "--now", "--tz", "--out"):
        window.add_argument(flag, required=True)
    start = window.add_mutually_exclusive_group()
    start.add_argument("--since", help="explicit window start, uncapped; the run then never advances the state")
    start.add_argument("--report-only", action="store_true", help="normal window start, marked explicit so the run never advances the state")
    seed = commands.add_parser("seed", help="turn the Run state of the newest live digest page into a tribe state")
    seed.add_argument("--page", action="append", required=True, help="saved fetch result of a digest page, newest first; repeatable")
    for flag in ("--routine", "--config", "--out"):
        seed.add_argument(flag, required=True)
    compute = commands.add_parser("features", help="write the features, base and rules files; decides nothing")
    for flag in ("--config", "--routine", "--state", "--window", "--collections", "--place", "--out", "--base-out", "--rules-out"):
        compute.add_argument(flag, required=True)
    judge = commands.add_parser("judge", help="check the judgment against the features; writes nothing")
    for flag in ("--features", "--judgment"):
        judge.add_argument(flag, required=True)
    apply = commands.add_parser("apply", help="merge the judgment and the page edits into the next state, the summary and the run record")
    for flag in ("--state", "--features", "--base", "--judgment", "--window", "--out", "--summary", "--record"):
        apply.add_argument(flag, required=True)
    add_publish_parsers(commands)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except state.InputError as error:
        print(f"tribe.py: {error}", file=sys.stderr)
        return 2
    except state.Rejected as error:
        print(f"tribe.py: rejected: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
