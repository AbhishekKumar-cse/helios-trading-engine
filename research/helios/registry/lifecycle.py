"""The life of an alpha: which state it is in, and which moves are legal (step 066).

```
DRAFT ──► SIMULATED ──► EVALUATED ──► PROMOTED ──► RETIRED
  │            │             │    └──► REJECTED ─► RETIRED
  └────────────┴─────────────┴──────► INVALID ───► RETIRED
```

Why a state machine at all: without one, an idea can be "promoted" straight from a sketch
with no simulation and no evaluation behind it. Writing the legal moves down once, in one
place, makes that impossible and makes the path of every alpha readable afterwards.

The rules encoded here:

- **nothing is promoted without being evaluated first**, and nothing is evaluated without
  being simulated first — the order is the whole point;
- **INVALID is reachable from anywhere before RETIRED**: discovering that a result was
  computed wrongly must always be allowed, at any stage;
- **RETIRED is the end**, so history stops changing;
- **no state moves to itself**, so "re-promoting" is never a silent no-op.

This is the state of *an idea* (one alpha version). It is not the same as the status of a
single evaluation run in `results.py`, which records what one measurement concluded.
"""

from __future__ import annotations

from enum import StrEnum


class IllegalTransition(Exception):
    """Raised when a move between states is not allowed."""


class AlphaState(StrEnum):
    """Where an alpha version stands."""

    DRAFT = "DRAFT"  # written down, nothing measured yet
    SIMULATED = "SIMULATED"  # positions and P&L computed on the simulator
    EVALUATED = "EVALUATED"  # metrics and gates computed out-of-sample
    PROMOTED = "PROMOTED"  # passed every gate; may be used by a strategy
    REJECTED = "REJECTED"  # failed a gate
    INVALID = "INVALID"  # the measurement itself was wrong (bug, bad data, leakage)
    RETIRED = "RETIRED"  # no longer in use; the record stays


ALLOWED: dict[AlphaState, frozenset[AlphaState]] = {
    AlphaState.DRAFT: frozenset({AlphaState.SIMULATED, AlphaState.INVALID}),
    AlphaState.SIMULATED: frozenset({AlphaState.EVALUATED, AlphaState.INVALID}),
    AlphaState.EVALUATED: frozenset({AlphaState.PROMOTED, AlphaState.REJECTED, AlphaState.INVALID}),
    AlphaState.PROMOTED: frozenset({AlphaState.RETIRED, AlphaState.INVALID}),
    AlphaState.REJECTED: frozenset({AlphaState.RETIRED, AlphaState.INVALID}),
    AlphaState.INVALID: frozenset({AlphaState.RETIRED}),
    AlphaState.RETIRED: frozenset(),
}

INITIAL = AlphaState.DRAFT
TERMINAL = AlphaState.RETIRED


def next_states(state: AlphaState) -> frozenset[AlphaState]:
    """Every state that may legally follow this one."""
    return ALLOWED[state]


def is_terminal(state: AlphaState) -> bool:
    """Whether the alpha has finished its life (nothing may follow)."""
    return not ALLOWED[state]


def can_move(current: AlphaState, target: AlphaState) -> bool:
    """Whether this move is allowed."""
    return target in ALLOWED[current]


def check_move(current: AlphaState, target: AlphaState) -> AlphaState:
    """Return `target` when the move is legal, otherwise explain why it is not."""
    if can_move(current, target):
        return target

    if is_terminal(current):
        raise IllegalTransition(
            f"{current} is the end of the line: nothing may follow it, so {target} is refused"
        )
    if current is target:
        raise IllegalTransition(f"{current} cannot move to itself")

    allowed = ", ".join(sorted(ALLOWED[current])) or "nothing"
    raise IllegalTransition(f"{current} cannot become {target}; allowed from here: {allowed}")


def apply_path(states: list[AlphaState], start: AlphaState = INITIAL) -> AlphaState:
    """Walk a sequence of moves from `start`, raising on the first illegal one."""
    current = start
    for target in states:
        current = check_move(current, target)
    return current


def reachable_from(state: AlphaState) -> frozenset[AlphaState]:
    """Every state that can eventually be reached from this one."""
    seen: set[AlphaState] = set()
    queue = [state]
    while queue:
        current = queue.pop()
        for following in ALLOWED[current]:
            if following not in seen:
                seen.add(following)
                queue.append(following)
    return frozenset(seen)
