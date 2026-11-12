"""CLI: python -m k22 verify --data data [--report report.json]."""

import argparse
import json
from pathlib import Path
import sys

from .verifier import (VerificationError, prepare_submission, read_json,
                       verify_dataset, write_json)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Independently verify matching source-torsion cores.")
    commands = parser.add_subparsers(dest="command", required=True)
    verify = commands.add_parser("verify", help="replay bounded, JSON-only mathematical certificates")
    verify.add_argument("--data", required=True, type=Path)
    verify.add_argument("--report", type=Path)
    prepare = commands.add_parser("prepare", help="verify a proof and write its correctly named submission")
    prepare.add_argument("--family", required=True, type=Path)
    prepare.add_argument("--matching", required=True, type=Path, help="JSON list of 242 oriented pairs")
    prepare.add_argument("--certificate", required=True, type=Path, help="k22-normal-closure-dag-v1 JSON")
    prepare.add_argument("--output", required=True, type=Path, help="existing submissions directory")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            family, _ = read_json(args.family)
            matching, _ = read_json(args.matching)
            certificate, _ = read_json(args.certificate)
            submission = prepare_submission(family, matching, certificate)
            path = args.output / (submission["submission_id"] + ".json")
            write_json(path, submission, exclusive=True)
            report = {"status": "PREPARED_AND_VERIFIED", "submission_id": submission["submission_id"],
                      "output": str(path), "optional_core_edges": len(submission["optional_core"])}
        else:
            report = verify_dataset(args.data)
            if args.report:
                # The report path is an explicit operator argument, never supplied by JSON.
                write_json(args.report, report)
    except (VerificationError, OSError) as error:
        print(json.dumps({"status": "REJECTED", "error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps({k: v for k, v in report.items() if k != "records"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
