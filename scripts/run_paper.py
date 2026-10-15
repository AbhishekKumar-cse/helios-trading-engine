"""Live public bars through shared simulated PAPER execution; never real orders."""

import argparse
import asyncio

from helios.paper.runner import run_paper


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, help="fresh unique session ID; never reused")
    parser.add_argument("--seconds", type=float, default=240)
    parser.add_argument("--endpoint", choices=("data", "spot443", "spot9443"), default="spot443")
    args = parser.parse_args()
    try:
        print(asyncio.run(run_paper(args.run_id, seconds=args.seconds, endpoint=args.endpoint)))
        return 0
    except KeyboardInterrupt:
        print("PAPER interrupted; inspect retained failure evidence")
        return 130
    except Exception as exc:
        print(f"PAPER failed: {type(exc).__name__}; inspect retained session evidence")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
