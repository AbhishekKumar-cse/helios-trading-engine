# Hourly final TEST and selection (139–140)

`scripts/final_test_hourly.py --execute` freezes a shortlist from each candidate's
latest VALID result before any TEST observation is loaded. It verifies registered
evidence hashes and alpha/version identity, requires clean source and all accepted
G1–G6 flags, and recomputes the gates from recorded metrics. It ranks by VALID
Fitness and keeps at most two (the helper hard limit is three). There is no
selection from TEST numbers or automatic retest after an earlier access.

An empty shortlist writes `SKIPPED_NO_ELIGIBLE_CANDIDATES`, empty outcomes and
the unchanged per-version counters. It does not preregister fake experiments,
load holdout observations or fabricate TEST results to satisfy a checkbox.
For eligible candidates, a new fixed confirmation experiment is preregistered
and evaluated through the existing simulator/gates. The existing atomic TEST
reservation commits **before** the data loader, with at most two total accesses
per alpha version. A failed/INVALID evaluation still consumes its reservation;
an exception abandons its experiment rather than erasing the attempt.

Current round-one evidence has eight INVALID candidate measurements; none is
eligible. Step 139 therefore completes the selection/TEST decision with a
documented skip. A genuine TEST measurement remains conditional on a future
valid candidate and cannot be claimed for this round.
