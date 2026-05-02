"""Tests for the per-target governance macros (P2R.11).

The macros — ``feature_set``, ``compile_grants``, ``compile_masking``
— dispatch on the active tier (``duckdb`` / ``standard`` /
``enterprise``). The default tier is the dbt target's adapter type;
an explicit ``catins_tier`` var wins when set, which lets these tests
exercise the Snowflake-tier branches against the DuckDB adapter
(snowflake-adapter is not installed in CI).

We verify three things per tier:
1. ``feature_set`` returns the expected capability flags.
2. ``compile_grants`` returns ``[]`` on tiers without grants and a
   ``GRANT SELECT ... TO ROLE`` post-hook string otherwise.
3. ``compile_masking`` returns the field unwrapped on tiers without
   masking, a ``CASE`` expression on the standard tier, and the field
   unwrapped on the enterprise tier (where masking is enforced by
   policy metadata, not by SQL).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

DBT_DIR = Path(__file__).resolve().parents[1] / "dbt"


def _run_governance_debug(
    tmp_path: Path,
    catins_tier: str | None,
) -> dict[str, str]:
    """Invoke ``_governance_debug`` and parse the captured key=value lines."""
    duckdb_path = tmp_path / "catins.duckdb"
    cmd = [
        "dbt",
        "run-operation",
        "_governance_debug",
        "--project-dir",
        str(DBT_DIR),
        "--profiles-dir",
        str(DBT_DIR),
    ]
    if catins_tier is not None:
        cmd.extend(["--vars", json.dumps({"catins_tier": catins_tier})])

    env = {
        **os.environ,
        "DBT_PROFILES_DIR": str(DBT_DIR),
        "CATINS_DUCKDB_PATH": str(duckdb_path),
    }
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)
    assert result.returncode == 0, (
        f"dbt run-operation failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )

    out: dict[str, str] = {}
    in_block = False
    for line in result.stdout.splitlines():
        # Strip ANSI colour escapes and dbt's timestamp prefix.
        clean = re.sub(r"\x1b\[[0-9;]*m", "", line).strip()
        clean = re.sub(r"^\d{2}:\d{2}:\d{2}\s+", "", clean)
        if clean == "GOVERNANCE_DEBUG_BEGIN":
            in_block = True
            continue
        if clean == "GOVERNANCE_DEBUG_END":
            break
        if in_block and "=" in clean:
            key, _, value = clean.partition("=")
            out[key] = value
    return out


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_duckdb_tier_no_governance(tmp_path: Path) -> None:
    """Default DuckDB target: all governance macros are no-ops."""
    out = _run_governance_debug(tmp_path, catins_tier=None)
    assert out["tier"] == "duckdb"
    assert out["masking"] == "none"
    assert out["row_access"] == "none"
    assert out["grants"] == "False"
    # Masking returns the field unwrapped — DuckDB tier asserts shape
    # parity, not access control.
    assert out["mask_direct"] == "holder_name"
    assert out["mask_quasi"] == "zip_code"
    # No GRANT post-hooks emitted on DuckDB.
    assert json.loads(out["grants_list"]) == []


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_standard_tier_emits_case_masking(tmp_path: Path) -> None:
    """Snowflake Standard: CASE-expression masking + GRANT post-hook."""
    out = _run_governance_debug(tmp_path, catins_tier="standard")
    assert out["tier"] == "standard"
    assert out["masking"] == "case_expression"
    assert out["row_access"] == "separate_view"
    assert out["grants"] == "True"
    # Direct PII masks to '***' for non-privacy-officer roles.
    assert "CASE WHEN IS_ROLE_IN_SESSION('PRIVACY_OFFICER')" in out["mask_direct"]
    assert "ELSE '***'" in out["mask_direct"]
    assert "holder_name" in out["mask_direct"]
    # Quasi PII nulls out for non-analyst non-officer roles.
    assert "ELSE NULL" in out["mask_quasi"]
    assert "zip_code" in out["mask_quasi"]
    # Grants emitted; the model-binding (``this``) is empty in
    # run-operation context, so we just assert the syntactic frame.
    grants = json.loads(out["grants_list"])
    assert len(grants) == 1
    assert grants[0].startswith("GRANT SELECT ON")
    assert "TO ROLE PRIVACY_OFFICER" in grants[0]


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_enterprise_tier_uses_policy_metadata(tmp_path: Path) -> None:
    """Snowflake Enterprise: masking is policy-attached, SQL stays clean."""
    out = _run_governance_debug(tmp_path, catins_tier="enterprise")
    assert out["tier"] == "enterprise"
    assert out["masking"] == "policy"
    assert out["row_access"] == "policy"
    assert out["grants"] == "True"
    # Masking emits the field unwrapped; the warehouse enforces the
    # MASKING POLICY attached to the column out-of-band.
    assert out["mask_direct"] == "holder_name"
    assert out["mask_quasi"] == "zip_code"
    # Same GRANT post-hook shape as the standard tier.
    grants = json.loads(out["grants_list"])
    assert len(grants) == 1
    assert grants[0].startswith("GRANT SELECT ON")
    assert "TO ROLE PRIVACY_OFFICER" in grants[0]


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_audit_view_emits_no_post_hook_on_duckdb(tmp_path: Path) -> None:
    """v_audit_erasures' compiled config.post-hook is empty on DuckDB.

    This is the integration-level proof that the model file's
    ``{{ config(post_hook=compile_grants(role='privacy_officer')) }}``
    expands to a no-op on the DuckDB tier — i.e., the model builds on
    a warehouse that doesn't have GRANT semantics, and only emits
    grants on tiers that do.
    """
    duckdb_path = tmp_path / "catins.duckdb"
    env = {
        **os.environ,
        "DBT_PROFILES_DIR": str(DBT_DIR),
        "CATINS_DUCKDB_PATH": str(duckdb_path),
    }
    result = subprocess.run(
        ["dbt", "parse", "--project-dir", str(DBT_DIR), "--profiles-dir", str(DBT_DIR)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    manifest = json.loads((DBT_DIR / "target" / "manifest.json").read_text())
    audit_node = next(n for n in manifest["nodes"].values() if n.get("name") == "v_audit_erasures")
    config = audit_node.get("config", {})
    # dbt normalises ``post_hook`` to ``post-hook`` in the manifest.
    assert config.get("post-hook") == []
