"""Validate and print one M7 JSONL trace; no model or machine access."""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from evaluation.tracing import format_trace, read_trace, validate_events  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("trace", help="path to a trace .jsonl file")
    parser.add_argument("--request", help="show only this request ID plus run-level events")
    args = parser.parse_args()
    events = read_trace(args.trace)
    problems = validate_events(events)
    if problems:
        for problem in problems:
            print(f"INVALID: {problem}", file=sys.stderr)
        return 1
    print(format_trace(events, args.request))
    return 0


if __name__ == "__main__":
    sys.exit(main())
