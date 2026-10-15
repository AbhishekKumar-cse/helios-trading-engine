"""Generate step 157's plot directly from the retained minute VALID artifacts."""

from pathlib import Path

from helios.common.db import get_engine
from helios.sim.minute_cost_report import build_report

if __name__ == "__main__":
    print(
        build_report(
            get_engine(),
            Path("reports_out/minute_round1/outcomes.json"),
            Path("reports_out/minute_cost_reality"),
        )
    )
