"""Planted-regression tests for check_guardrail_stability (P3.5).

Phase 3 done condition #3: "A planted regression — e.g., a feature
pipeline silently missing a column — is caught by an asset check
inside one nightly cycle, not in the next compliance review."

The schema-drift case is covered in test_schema_drift_check.py
(P3.4); this file covers the analogous guardrail-distribution case.
The check fails when the mean of the risk-score component of the
joint payload crosses ``MAX_PORTFOLIO_RISK_SCORE`` — a silent shift
in the guardrail distribution that would not register as a
governance failure (no rule fires) but indicates the portfolio is
shifting toward higher aggregate risk than the underwriting model
expects.
"""

import pandas as pd

from catins.orchestration.checks import (
    MAX_PORTFOLIO_RISK_SCORE,
    _evaluate_guardrail_stability,
)


def _df_with_scores(scores: list[float]) -> pd.DataFrame:
    """Build a validated_outcomes-shaped DataFrame with the given risk scores."""
    payloads = [([], score) for score in scores]
    return pd.DataFrame({"payload": payloads, "admitted": [True] * len(scores)})


def test_passes_on_low_risk_portfolio() -> None:
    df = _df_with_scores([0.1, 0.2, 0.0, 0.3, 0.1])
    result = _evaluate_guardrail_stability(df)
    assert result.passed
    assert result.description is not None
    assert "<" in result.description


def test_fails_on_planted_high_risk_batch() -> None:
    """A simulated upstream regression that pushes the guardrail mean up.

    The batch could result from a feature pipeline silently emitting
    higher-risk values, a misclassified rating factor, or a
    distributional shift in the input data. The asset check fires
    before any contracts are issued under the regressed regime.
    """
    df = _df_with_scores([0.7, 0.8, 0.6, 0.9])
    result = _evaluate_guardrail_stability(df)
    assert not result.passed
    assert result.description is not None
    assert ">=" in result.description
    assert f"cap {MAX_PORTFOLIO_RISK_SCORE}" in result.description


def test_boundary_exactly_at_cap_fails() -> None:
    """The check fires at >= cap, not strictly >, so equality fails."""
    cap = MAX_PORTFOLIO_RISK_SCORE
    df = _df_with_scores([cap, cap])
    result = _evaluate_guardrail_stability(df)
    assert not result.passed


def test_boundary_just_below_cap_passes() -> None:
    cap = MAX_PORTFOLIO_RISK_SCORE
    df = _df_with_scores([cap - 0.01, cap - 0.01])
    result = _evaluate_guardrail_stability(df)
    assert result.passed


def test_empty_dataframe_passes() -> None:
    """An empty input is not a regression; the check passes vacuously."""
    df = pd.DataFrame({"payload": [], "admitted": []})
    result = _evaluate_guardrail_stability(df)
    assert result.passed
    assert result.description is not None
    assert "No scores" in result.description


def test_single_outlier_does_not_trip_check() -> None:
    """A single high-risk row does not breach the *mean* threshold.

    The check is a population-mean drift signal, not a per-row
    governance check. A single spike is absorbed by the mean.
    """
    df = _df_with_scores([0.0, 0.0, 0.0, 0.0, 1.0])  # mean = 0.2
    result = _evaluate_guardrail_stability(df)
    assert result.passed
