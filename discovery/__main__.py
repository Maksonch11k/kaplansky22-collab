"""Local steps driven by the LLM in an existing chat; no API connection."""
import argparse
import json
from pathlib import Path
import sys

from .cycle import advance_run, demo_run, read_state, start_run, summary
from .data_merge import merge_data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("start", help="Generate a candidate and a prompt for the chat agent")
    start.add_argument("--output", required=True, type=Path)
    start.add_argument("--data", default=Path("data"), type=Path)
    start.add_argument("--family", default="trinomial22", choices=("parallel22", "trinomial22"))
    start.add_argument("--rounds", type=int, default=3)
    start.add_argument("--seed", type=int, default=22)
    start.add_argument("--population", type=int, default=32)
    start.add_argument("--epochs", type=int, default=2)
    start.add_argument("--max-operations", type=int, default=20000)
    start.add_argument("--max-rules", type=int, default=2000)
    start.add_argument("--max-seconds", type=float, default=10)
    start.add_argument("--candidate", type=Path, help="Optional explicit first candidate; generation is otherwise automatic")
    advance = commands.add_parser("advance", help="Check a chat proposal, search, verify, feed back and prepare the next round")
    advance.add_argument("--run", required=True, type=Path)
    advance.add_argument("--proposal", required=True, type=Path)
    status = commands.add_parser("status", help="Show saved progress without running search")
    status.add_argument("--run", required=True, type=Path)
    demo = commands.add_parser("demo", help="Offline rediscovery of a known core using a hand-authored proposal")
    demo.add_argument("--output", required=True, type=Path)
    demo.add_argument("--data", default=Path("data"), type=Path)
    merge = commands.add_parser("merge-data", help="Verify and combine a base atlas with saved feedback for a new run")
    merge.add_argument("--base", required=True, type=Path)
    merge.add_argument("--feedback", required=True, type=Path)
    merge.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            result = start_run(args.output, data=args.data, family_id=args.family, rounds=args.rounds,
                seed=args.seed, population=args.population, epochs=args.epochs,
                max_operations=args.max_operations, max_rules=args.max_rules, max_seconds=args.max_seconds,
                candidate=args.candidate)
        elif args.command == "advance":
            result = advance_run(args.run, args.proposal)
        elif args.command == "demo":
            result = demo_run(args.output, data=args.data)
        elif args.command == "merge-data":
            result = merge_data(args.base, args.feedback, args.output)
        else:
            result = summary(read_state(args.run))
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"status": "REJECTED", "error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
