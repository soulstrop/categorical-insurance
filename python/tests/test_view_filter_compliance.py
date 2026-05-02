"""Tests for the view-filter compliance asset check (P3.11).

The check (``orchestration.checks._evaluate_view_filter_compliance``)
implements ADR 007 §2 at the Dagster layer: every consumer-facing view
in the dbt project (model under ``models/marts/`` materialised as a
view) must contain a literal ``WHERE erased = false`` predicate in its
compiled SQL. Equivalents like ``NOT erased`` are intentionally
rejected — a single canonical form keeps grep, review, and the check
aligned.
"""

from typing import Any

from catins.orchestration.checks import (
    _evaluate_view_filter_compliance,
    _has_erasure_filter,
)


def _model_node(
    path: str,
    sql: str,
    materialized: str = "view",
) -> dict[str, Any]:
    return {
        "resource_type": "model",
        "config": {"materialized": materialized, "tags": []},
        "original_file_path": path,
        "compiled_code": sql,
    }


def test_filter_regex_matches_canonical_form() -> None:
    assert _has_erasure_filter("SELECT * FROM t WHERE erased = false")


def test_filter_regex_matches_uppercase_false() -> None:
    assert _has_erasure_filter("SELECT * FROM t WHERE erased = FALSE")


def test_filter_regex_matches_no_spaces() -> None:
    assert _has_erasure_filter("SELECT * FROM t WHERE erased=false")


def test_filter_regex_rejects_negation_form() -> None:
    # `NOT erased` is logically equivalent but ADR 007 §2 prescribes the
    # literal `erased = false` form — the check is a *convention*
    # enforcer, not a logic checker.
    assert not _has_erasure_filter("SELECT * FROM t WHERE NOT erased")


def test_filter_regex_rejects_no_filter() -> None:
    assert not _has_erasure_filter("SELECT * FROM t")


def test_filter_regex_accepts_macro_reference() -> None:
    """Raw dbt template form (pre-compile) — the macro reference itself
    is sufficient evidence the filter is composed in."""
    assert _has_erasure_filter("SELECT * FROM t WHERE {{ erasure_filter() }}")


def test_filter_regex_accepts_macro_reference_with_whitespace() -> None:
    """Whitespace inside the Jinja braces survives the regex."""
    assert _has_erasure_filter("SELECT * FROM t WHERE {{  erasure_filter()  }}")


def test_no_consumer_views_passes_vacuously() -> None:
    """Today's repo state: only staging models, no marts/. Should pass."""
    manifest = {
        "nodes": {
            "model.catins.stg_proposals": _model_node(
                "models/staging/stg_proposals.sql",
                "SELECT * FROM raw.proposals",
            ),
        },
    }
    result = _evaluate_view_filter_compliance(manifest)
    assert result.passed
    assert result.description is not None
    assert "No consumer-facing views" in result.description


def test_consumer_view_with_filter_passes() -> None:
    manifest = {
        "nodes": {
            "model.catins.v_proposals": _model_node(
                "models/marts/v_proposals.sql",
                "SELECT * FROM stg_proposals WHERE erased = false",
            ),
        },
    }
    result = _evaluate_view_filter_compliance(manifest)
    assert result.passed
    assert result.description is not None
    assert "All 1 consumer-facing views filter" in result.description


def test_consumer_view_without_filter_fails() -> None:
    manifest = {
        "nodes": {
            "model.catins.v_proposals": _model_node(
                "models/marts/v_proposals.sql",
                "SELECT * FROM stg_proposals",
            ),
        },
    }
    result = _evaluate_view_filter_compliance(manifest)
    assert not result.passed
    assert result.description is not None
    assert "model.catins.v_proposals" in result.description
    assert "missing" in result.description


def test_mixed_consumer_views_reports_only_offenders() -> None:
    manifest = {
        "nodes": {
            "model.catins.v_good": _model_node(
                "models/marts/v_good.sql",
                "SELECT * FROM stg WHERE erased = false",
            ),
            "model.catins.v_bad": _model_node(
                "models/marts/v_bad.sql",
                "SELECT * FROM stg",
            ),
        },
    }
    result = _evaluate_view_filter_compliance(manifest)
    assert not result.passed
    assert result.description is not None
    assert "1/2 consumer-facing views" in result.description
    assert "model.catins.v_bad" in result.description
    assert "model.catins.v_good" not in result.description


def test_marts_table_skipped() -> None:
    """Tables in marts/ are managed by the cleaning sweep, not the view filter."""
    manifest = {
        "nodes": {
            "model.catins.t_some_table": _model_node(
                "models/marts/t_some_table.sql",
                "SELECT * FROM stg",
                materialized="table",
            ),
        },
    }
    result = _evaluate_view_filter_compliance(manifest)
    assert result.passed
    assert result.description is not None
    assert "No consumer-facing views" in result.description


def test_staging_view_skipped() -> None:
    """Staging models are intermediate, not consumer-facing."""
    manifest = {
        "nodes": {
            "model.catins.stg_proposals": _model_node(
                "models/staging/stg_proposals.sql",
                "SELECT * FROM raw",
            ),
        },
    }
    result = _evaluate_view_filter_compliance(manifest)
    assert result.passed


def test_non_model_nodes_ignored() -> None:
    """Tests, sources, and other resource types are not models."""
    manifest = {
        "nodes": {
            "test.catins.not_null_v_x_holder": {
                "resource_type": "test",
                "config": {"materialized": "test", "tags": []},
                "original_file_path": "models/marts/schema.yml",
                "compiled_code": "SELECT holder FROM v_x WHERE holder IS NULL",
            },
        },
    }
    result = _evaluate_view_filter_compliance(manifest)
    assert result.passed
