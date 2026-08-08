from pathlib import Path

from sqlalchemy import Index, UniqueConstraint

from src.api.cards.repository.model import (
    Card,
    CardListing,
    ScrapeJob,
    ScrapeTarget,
    SearchIndexEvent,
)


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
        "search_index_events",
    ):
        assert f'"{table_name}"' in source
    assert source.count("include_name=include_name") == 2


def test_model_metadata_matches_historical_server_defaults() -> None:
    expected = {
        CardListing: ("source", "currency", "stock", "is_active"),
        ScrapeTarget: (
            "last_requested_at",
            "last_result_count",
            "last_in_stock_count",
            "is_enabled",
        ),
        ScrapeJob: ("status", "priority", "attempts", "available_at"),
        SearchIndexEvent: ("status", "attempts", "available_at"),
    }
    for model, column_names in expected.items():
        for column_name in column_names:
            assert model.__table__.c[column_name].server_default is not None


def test_model_metadata_keeps_separate_unique_constraints_and_indexes() -> None:
    expected = {
        Card: (("uq_cards_ygo_id",), ("ix_cards_ygo_id",)),
        ScrapeTarget: (
            ("uq_scrape_targets_card_id", "uq_scrape_targets_ygo_id"),
            ("ix_scrape_targets_card_id", "ix_scrape_targets_ygo_id"),
        ),
    }
    for model, (constraint_names, index_names) in expected.items():
        constraints = {
            constraint.name
            for constraint in model.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        indexes = {
            index.name: index
            for index in model.__table__.indexes
            if isinstance(index, Index)
        }
        assert set(constraint_names) <= constraints
        assert set(index_names) <= indexes.keys()
        assert all(not indexes[name].unique for name in index_names)
