from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_ENV = PROJECT_ROOT / "migrations" / "env.py"


def test_search_uses_an_independent_alembic_version_table() -> None:
    source = ALEMBIC_ENV.read_text(encoding="utf-8")

    assert 'VERSION_TABLE = "free_win_search_alembic_version"' in source
    assert source.count("version_table=VERSION_TABLE") == 2


def test_autogenerate_is_limited_to_search_owned_tables() -> None:
    source = ALEMBIC_ENV.read_text(encoding="utf-8")

    for table_name in (
        "cards",
        "card_listings",
        "scrape_targets",
        "scrape_jobs",
    ):
        assert f'"{table_name}"' in source
    assert source.count("include_name=include_name") == 2
