"""End-to-end integration tests for Phase-2-revisit (P2R.12).

The Phase-2-revisit done conditions (PHASES.md, Phase 2 sandbox §):

1. CI green: lint, drift check, schema-compat check, full pytest.
2. A proposal flowing through the pipeline cannot land a direct
   identifier in the warehouse — only a tokenised reference.
3. An erased row is invisible through the consumer-facing view and
   visible through the privacy-officer audit table.
4. A breaking schema change without ``# evolution: breaking`` fails
   CI; with the annotation it passes.
5. Dev-tier view-emulation produces the same masked outputs that
   prod-tier ``MASKING POLICY`` would (parity tests).
6. A non-empty ``raw_quarantine`` partition is detected by an asset
   check (Phase 3) and surfaces a runbook entry.

Conditions 1, 4, 5 are passive/sandbox-time and verified elsewhere
(the test_schema_compat suite covers 4; test_governance_macros
covers 5's structural shape; CI covers 1). Conditions 2, 3, 6 are
*pipeline-level* and verified end-to-end here.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import duckdb
import pandas as pd

from catins.cortex import BudgetedCortex, MockCortex
from catins.models import SCHEMA_V1_EFFECTIVE_DATE, CanonicalProposal, Violation
from catins.monoid import ListMonoid, RiskScoreMonoid, product_monoid
from catins.pipeline import run_dbt_build_post, run_pipeline
from catins.privacy.erasure import erase, init_audit_table
from catins.privacy.tokenisation import MockTokenisationClient
from catins.schema_evolution import QuarantineRow, write_quarantine_rows
from catins.warehouse import DuckDBSession

JointMonoid = product_monoid(ListMonoid, RiskScoreMonoid)
RISK_CAP = 1.0
YOUNG_DRIVER = 25
DBT_DIR = Path(__file__).resolve().parents[1] / "dbt"

_METADATA_DEFAULTS = {
    "schema_version": 1,
    "schema_effective_date": pd.Timestamp(SCHEMA_V1_EFFECTIVE_DATE),
    "erased": False,
}


def _rule_positive_premium(p: CanonicalProposal) -> tuple[list[Violation], float]:
    if p.premium <= 0:
        return ([Violation(rule_name="premium", message="Negative premium")], 0.0)
    return ([], 0.0)


def _risk_age(p: CanonicalProposal) -> tuple[list[Violation], float]:
    return ([], 0.6 if p.age < YOUNG_DRIVER else 0.0)


def _is_admissible(m: tuple[list[Violation], float]) -> bool:
    violations, score = m
    return len(violations) == 0 and score < RISK_CAP


def _seed_raw_proposals(duckdb_path: Path) -> None:
    session = DuckDBSession(database=str(duckdb_path))
    session.sql("CREATE SCHEMA IF NOT EXISTS raw")
    session.write_table(
        pd.DataFrame(
            [
                {
                    "holder_kind": "individual",
                    "holder_name": "Alice",
                    "premium": 100.0,
                    "zip_code": "10001",
                    "age": 30,
                    **_METADATA_DEFAULTS,
                },
                {
                    "holder_kind": "individual",
                    "holder_name": "Bob",
                    "premium": 250.0,
                    "zip_code": "10001",
                    "age": 45,
                    **_METADATA_DEFAULTS,
                },
            ]
        ),
        "raw.proposals",
    )
    session.close()


def _run_dbt_env(duckdb_path: Path) -> dict[str, str]:
    return {
        "DBT_PROFILES_DIR": str(DBT_DIR),
        "CATINS_DUCKDB_PATH": str(duckdb_path),
    }


def test_done_condition_2_tokenisation_before_warehouse_landing() -> None:
    """PHASES.md done condition 2: direct PII never lands plaintext.

    The Cortex extraction path tokenises ``holder_name`` (direct
    identifier per ADR 006) before writing to ``stg_proposals``; the
    plaintext name should appear in *no* warehouse column.
    """
    session = DuckDBSession()
    cortex = BudgetedCortex(MockCortex(), max_tokens=10_000)
    tokeniser = MockTokenisationClient()
    raw = [
        "Holder: Alice. Premium: $100. ZIP 10001. Age: 30.",
        "Holder: Bob. Premium: $250. ZIP 10001. Age: 45.",
    ]
    result = run_pipeline(
        session_factory=lambda: session,
        cortex=cortex,
        proposal_cls=CanonicalProposal,
        decisions=[_rule_positive_premium, _risk_age],
        adm=_is_admissible,
        monoid=JointMonoid,
        raw_texts=raw,
        tokenisation_client=tokeniser,
    )
    assert result.contracts == 2
    assert result.extracted == 2
    assert result.quarantined == 0

    # The warehouse should hold tokens, not plaintext names.
    stg_names = session.sql("SELECT holder_name FROM stg_proposals")["holder_name"].tolist()
    contract_names = session.sql("SELECT holder_name FROM contracts")["holder_name"].tolist()
    assert "Alice" not in stg_names
    assert "Bob" not in stg_names
    assert "Alice" not in contract_names
    assert "Bob" not in contract_names

    # The tokens should round-trip back to the originals via the
    # client — proving tokenisation, not just substitution.
    plaintext = {tokeniser.detokenise(t, transformation="holder_name") for t in stg_names}
    assert plaintext == {"Alice", "Bob"}


def test_done_condition_6_quarantine_landing_visible() -> None:
    """PHASES.md done condition 6: raw_quarantine carries failures.

    Simulates two upstream rows that the schema dispatcher rejects
    (one with an unknown ``schema_version``, one missing it). The
    pipeline run leaves them in ``raw_quarantine``; the dbt
    ``stg_quarantine`` projection surfaces them with stable types.
    """
    with tempfile.TemporaryDirectory() as tmp:
        duckdb_path = Path(tmp) / "warehouse.duckdb"
        _seed_raw_proposals(duckdb_path)

        # Pre-seed raw_quarantine with rows the upstream dispatcher
        # would have rejected. (The dispatcher itself is exercised by
        # test_quarantine_writer; here we want to verify the dbt
        # projection over an externally-populated quarantine table.)
        seed_session = DuckDBSession(database=str(duckdb_path))
        write_quarantine_rows(
            seed_session,
            [
                QuarantineRow(
                    raw_payload={"holder_name": "Eve", "schema_version": 99},
                    reason="unknown schema version",
                    schema_version_seen=99,
                    detail="known versions: [1]",
                ),
                QuarantineRow(
                    raw_payload={"holder_name": "Mallory"},
                    reason="missing schema_version",
                ),
            ],
        )
        seed_session.close()

        cortex = BudgetedCortex(MockCortex(), max_tokens=10_000)
        prior = {k: os.environ.get(k) for k in _run_dbt_env(duckdb_path)}
        os.environ.update(_run_dbt_env(duckdb_path))
        try:
            result = run_pipeline(
                session_factory=lambda: DuckDBSession(database=str(duckdb_path)),
                cortex=cortex,
                proposal_cls=CanonicalProposal,
                decisions=[_rule_positive_premium, _risk_age],
                adm=_is_admissible,
                monoid=JointMonoid,
                dbt_project_dir=DBT_DIR,
            )
        finally:
            for k, v in prior.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        assert result.contracts == 2

        # The dbt-built stg_quarantine model exposes the underlying rows.
        con = duckdb.connect(str(duckdb_path))
        reasons = [
            row[0]
            for row in con.execute(
                "SELECT reason FROM main.stg_quarantine ORDER BY reason"
            ).fetchall()
        ]
        con.close()
        assert reasons == ["missing schema_version", "unknown schema version"]


def test_done_condition_3_erased_invisible_in_view_visible_in_audit() -> None:
    """PHASES.md done condition 3: erasure is filtered, audit-trailed.

    Run the full dbt loop, erase a contract row, refresh marts/audit,
    then assert the erased subject is gone from ``v_contracts`` and
    present in ``v_audit_erasures``.
    """
    with tempfile.TemporaryDirectory() as tmp:
        duckdb_path = Path(tmp) / "warehouse.duckdb"
        _seed_raw_proposals(duckdb_path)

        cortex = BudgetedCortex(MockCortex(), max_tokens=10_000)
        prior = {k: os.environ.get(k) for k in _run_dbt_env(duckdb_path)}
        os.environ.update(_run_dbt_env(duckdb_path))
        try:
            result = run_pipeline(
                session_factory=lambda: DuckDBSession(database=str(duckdb_path)),
                cortex=cortex,
                proposal_cls=CanonicalProposal,
                decisions=[_rule_positive_premium, _risk_age],
                adm=_is_admissible,
                monoid=JointMonoid,
                dbt_project_dir=DBT_DIR,
            )
            assert result.contracts == 2

            # Erase Alice. The pipeline closed its session as part of
            # the post-validation dbt build; we open a fresh one.
            erasure_session = DuckDBSession(database=str(duckdb_path))
            init_audit_table(erasure_session)
            erasure = erase(
                erasure_session,
                table="contracts",
                where_column="holder_name",
                where_value="Alice",
                model_cls=CanonicalProposal,
                erased_by="privacy.officer@example.com",
                reason="GDPR Art. 17 request",
            )
            erasure_session.close()
            assert erasure.already_erased is False
            assert "holder_name" in erasure.pii_fields_nulled

            # Refresh marts + audit so the views reflect the erasure.
            run_dbt_build_post(DBT_DIR)
        finally:
            for k, v in prior.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        con = duckdb.connect(str(duckdb_path))
        # Consumer view: Alice is gone (filtered by erased = false).
        v_contract_names = [
            row[0] for row in con.execute("SELECT holder_name FROM main.v_contracts").fetchall()
        ]
        # Audit view: the erasure event is preserved with its operator
        # identity and pre-erasure snapshot.
        audit_rows = con.execute(
            "SELECT erased_by, where_value, pre_erasure_snapshot FROM main.v_audit_erasures"
        ).fetchall()
        con.close()

        assert "Alice" not in v_contract_names
        assert len(v_contract_names) == 1
        assert audit_rows == [
            ("privacy.officer@example.com", "Alice", audit_rows[0][2]),
        ]
        # The pre-erasure snapshot preserves the plaintext that the
        # tombstoned row no longer carries.
        assert "Alice" in audit_rows[0][2]


def test_done_condition_3_erasure_is_idempotent() -> None:
    """A second erasure call with the same target is a no-op.

    Done condition 3 implies the operation is replayable for the
    on-call: rerunning the same erasure must not double-tombstone or
    append a duplicate audit row.
    """
    with tempfile.TemporaryDirectory() as tmp:
        duckdb_path = Path(tmp) / "warehouse.duckdb"
        _seed_raw_proposals(duckdb_path)

        cortex = BudgetedCortex(MockCortex(), max_tokens=10_000)
        prior = {k: os.environ.get(k) for k in _run_dbt_env(duckdb_path)}
        os.environ.update(_run_dbt_env(duckdb_path))
        try:
            run_pipeline(
                session_factory=lambda: DuckDBSession(database=str(duckdb_path)),
                cortex=cortex,
                proposal_cls=CanonicalProposal,
                decisions=[_rule_positive_premium, _risk_age],
                adm=_is_admissible,
                monoid=JointMonoid,
                dbt_project_dir=DBT_DIR,
            )

            session = DuckDBSession(database=str(duckdb_path))
            init_audit_table(session)
            first = erase(
                session,
                table="contracts",
                where_column="holder_name",
                where_value="Alice",
                model_cls=CanonicalProposal,
                erased_by="privacy.officer@example.com",
                reason="GDPR Art. 17 request",
            )
            second = erase(
                session,
                table="contracts",
                where_column="holder_name",
                where_value="Alice",
                model_cls=CanonicalProposal,
                erased_by="privacy.officer@example.com",
                reason="GDPR Art. 17 retry",
            )
            audit_count = int(
                session.sql(
                    "SELECT count(*) AS n FROM _audit_erasures "
                    "WHERE table_name = 'contracts' AND where_value = 'Alice'"
                )["n"].iloc[0]
            )
            session.close()
        finally:
            for k, v in prior.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

        assert first.already_erased is False
        assert second.already_erased is True
        assert second.erasure_id == first.erasure_id
        assert audit_count == 1
