import pytest

from sql_guard import SQLGuard


def test_guard_allows_any_curated_relation() -> None:
    guard = SQLGuard({"curated"})
    guard.validate("SELECT * FROM curated.qualquer_tabela LIMIT 10")


def test_guard_allows_curated_joins() -> None:
    guard = SQLGuard({"curated"})
    guard.validate(
        "SELECT a.id, b.total "
        "FROM curated.a AS a "
        "JOIN curated.b AS b ON b.id = a.id "
        "LIMIT 10"
    )


def test_guard_blocks_write_sql() -> None:
    guard = SQLGuard({"curated"})
    with pytest.raises(ValueError):
        guard.validate("DELETE FROM curated.vw_pnp_vanna_resumo")


def test_guard_blocks_raw_schema() -> None:
    guard = SQLGuard({"curated"})
    with pytest.raises(ValueError):
        guard.validate("SELECT * FROM raw.x")


def test_guard_blocks_public_schema() -> None:
    guard = SQLGuard({"curated"})
    with pytest.raises(ValueError):
        guard.validate("SELECT * FROM public.x")


def test_guard_blocks_information_schema() -> None:
    guard = SQLGuard({"curated"})
    with pytest.raises(ValueError):
        guard.validate("SELECT * FROM information_schema.tables")


def test_guard_blocks_unqualified_relation() -> None:
    guard = SQLGuard({"curated"})
    with pytest.raises(ValueError):
        guard.validate("SELECT * FROM vw_pnp_vanna_resumo")


def test_guard_blocks_disallowed_schema_in_comma_join() -> None:
    guard = SQLGuard({"curated"})
    with pytest.raises(ValueError):
        guard.validate("SELECT * FROM curated.a, other_schema.b")


def test_guard_blocks_raw_schema_even_when_not_in_from() -> None:
    guard = SQLGuard({"curated"})
    with pytest.raises(ValueError):
        guard.validate("SELECT raw.pnp_runs.id FROM curated.vw_pnp_vanna_resumo")


def test_guard_blocks_multiple_statements() -> None:
    guard = SQLGuard({"curated"})
    with pytest.raises(ValueError):
        guard.validate("SELECT * FROM curated.vw_pnp_vanna_resumo; SELECT * FROM raw.pnp_runs")


def test_guard_adds_limit_when_missing() -> None:
    guard = SQLGuard({"curated"})
    sql = guard.enforce_limit("SELECT * FROM curated.vw_pnp_vanna_resumo", 25)
    assert sql.endswith("LIMIT 25")
