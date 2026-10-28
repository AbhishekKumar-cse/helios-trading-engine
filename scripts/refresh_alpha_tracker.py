"""Refresh the ignored local evidence inventory after a supported research run."""

from helios.common.lineage import PROJECT_ROOT
from helios.dashboard.alpha_tracker import refresh_tracker

if __name__ == "__main__":
    rows, issues = refresh_tracker(PROJECT_ROOT)
    print(f"Tracker saved: {len(rows)} verified rows, {len(issues)} source notices.")
    for issue in issues:
        print(issue)
