"""Tests for the alpha state machine (step 066).

Half of these are ordinary examples. The other half use **hypothesis**, which invents
thousands of random paths through the machine and checks that a property holds for all of
them. That is much stronger than a handful of hand-written cases: it is how you find the
path nobody thought of.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from helios.registry.lifecycle import (
    ALLOWED,
    INITIAL,
    TERMINAL,
    AlphaState,
    IllegalTransition,
    apply_path,
    can_move,
    check_move,
    is_terminal,
    next_states,
    reachable_from,
)

states = st.sampled_from(list(AlphaState))
HAPPY_PATH = [AlphaState.SIMULATED, AlphaState.EVALUATED, AlphaState.PROMOTED]


# ---------------------------------------------------------------- the normal journey


def test_the_happy_path_works() -> None:
    assert apply_path(HAPPY_PATH) is AlphaState.PROMOTED


def test_a_promoted_alpha_can_be_retired() -> None:
    assert apply_path([*HAPPY_PATH, AlphaState.RETIRED]) is AlphaState.RETIRED


def test_a_failing_alpha_is_rejected_then_retired() -> None:
    path = [AlphaState.SIMULATED, AlphaState.EVALUATED, AlphaState.REJECTED, AlphaState.RETIRED]
    assert apply_path(path) is AlphaState.RETIRED


def test_every_alpha_starts_as_a_draft() -> None:
    assert INITIAL is AlphaState.DRAFT
    assert apply_path([]) is AlphaState.DRAFT


# ---------------------------------------------------------------- the moves that must fail


def test_a_draft_cannot_be_promoted() -> None:
    """The reason this machine exists: no promotion without evidence behind it."""
    with pytest.raises(IllegalTransition, match="DRAFT cannot become PROMOTED"):
        check_move(AlphaState.DRAFT, AlphaState.PROMOTED)


def test_simulation_cannot_be_skipped() -> None:
    with pytest.raises(IllegalTransition, match="DRAFT cannot become EVALUATED"):
        check_move(AlphaState.DRAFT, AlphaState.EVALUATED)


def test_a_rejected_alpha_cannot_become_promoted() -> None:
    """Disappointing news cannot be turned around by changing a word."""
    with pytest.raises(IllegalTransition, match="REJECTED cannot become PROMOTED"):
        check_move(AlphaState.REJECTED, AlphaState.PROMOTED)


def test_a_retired_alpha_cannot_come_back() -> None:
    with pytest.raises(IllegalTransition, match="end of the line"):
        check_move(AlphaState.RETIRED, AlphaState.PROMOTED)


def test_the_error_lists_what_is_allowed() -> None:
    with pytest.raises(IllegalTransition) as failure:
        check_move(AlphaState.DRAFT, AlphaState.RETIRED)
    assert "allowed from here: INVALID, SIMULATED" in str(failure.value)


def test_a_path_stops_at_the_first_illegal_move() -> None:
    with pytest.raises(IllegalTransition, match="SIMULATED cannot become PROMOTED"):
        apply_path([AlphaState.SIMULATED, AlphaState.PROMOTED])


# ---------------------------------------------------------------- properties (hypothesis)


@given(states)
def test_no_state_can_move_to_itself(state: AlphaState) -> None:
    """Otherwise 're-promoting' would look like progress while changing nothing."""
    assert not can_move(state, state)


@given(states)
def test_every_state_can_reach_the_end(state: AlphaState) -> None:
    """No alpha can get stuck somewhere it can never leave."""
    assert state is TERMINAL or TERMINAL in reachable_from(state)


@given(states)
def test_a_mistake_can_always_be_admitted(state: AlphaState) -> None:
    """INVALID must be reachable from every state except the end."""
    assert state in (AlphaState.INVALID, TERMINAL) or AlphaState.INVALID in next_states(state)


@given(states, states)
def test_a_move_is_allowed_exactly_when_the_table_says_so(
    current: AlphaState, target: AlphaState
) -> None:
    assert can_move(current, target) == (target in ALLOWED[current])


@given(states, states)
def test_an_illegal_move_always_raises(current: AlphaState, target: AlphaState) -> None:
    if can_move(current, target):
        assert check_move(current, target) is target
    else:
        with pytest.raises(IllegalTransition):
            check_move(current, target)


@given(st.lists(states, max_size=8))
def test_a_path_either_finishes_in_a_real_state_or_raises(path: list[AlphaState]) -> None:
    """Whatever sequence is thrown at it, the machine never ends up somewhere undefined."""
    try:
        end = apply_path(path)
    except IllegalTransition:
        return
    assert end in AlphaState
    assert end in {INITIAL, *reachable_from(INITIAL)}


@given(st.lists(states, min_size=1, max_size=8))
def test_promotion_always_has_evaluation_behind_it(path: list[AlphaState]) -> None:
    """The safety property: no legal path reaches PROMOTED without passing EVALUATED."""
    try:
        apply_path(path)
    except IllegalTransition:
        return
    if AlphaState.PROMOTED in path:
        promoted_at = path.index(AlphaState.PROMOTED)
        assert AlphaState.EVALUATED in path[:promoted_at]
        assert AlphaState.SIMULATED in path[:promoted_at]


@given(st.lists(states, min_size=1, max_size=8))
def test_nothing_happens_after_retirement(path: list[AlphaState]) -> None:
    try:
        apply_path(path)
    except IllegalTransition:
        return
    if TERMINAL in path:
        assert path.index(TERMINAL) == len(path) - 1  # it can only be the last move


# ---------------------------------------------------------------- the table itself


def test_every_state_appears_in_the_table() -> None:
    assert set(ALLOWED) == set(AlphaState)


def test_only_retired_is_terminal() -> None:
    terminal = [state for state in AlphaState if is_terminal(state)]
    assert terminal == [AlphaState.RETIRED]


def test_every_state_is_reachable_from_the_start() -> None:
    assert reachable_from(INITIAL) == set(AlphaState) - {INITIAL}
