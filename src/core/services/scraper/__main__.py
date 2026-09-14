import argparse
import asyncio
import json
import logging
from dataclasses import asdict
from pathlib import Path

from src.api.cards.repository.scrape_jobs import reset_target
from src.core.db.deps import async_session_factory
from src.settings.scraper_settings import scraper_settings

from .backfill import (
    BackfillConfig,
    BackfillStateError,
    config_from_settings,
    run_full_catalog_refresh,
    run_missing_listings_backfill,
)
from .worker import run_once, run_worker


async def _reset_target(*, card_id: int | None, ygo_id: int | None) -> int:
    async with async_session_factory() as db:
        target = await reset_target(db, card_id=card_id, ygo_id=ygo_id)

    if target is None:
        print("No scrape target matched the supplied identifier.")

        return 1

    print(
        json.dumps(
            {
                "card_id": target.card_id,
                "ygo_id": target.ygo_id,
                "is_enabled": target.is_enabled,
            }
        )
    )

    return 0


def _add_schedule_arguments(
    parser: argparse.ArgumentParser,
    *,
    default_state_path: Path,
) -> None:
    parser.add_argument("--state-file", type=Path, default=default_state_path)
    parser.add_argument("--batch-size", type=int)
    parser.add_argument(
        "--min-interval-minutes",
        type=int,
        help="Minimum delay between batches",
    )
    parser.add_argument(
        "--max-interval-minutes",
        type=int,
        help="Maximum delay between batches",
    )
    parser.add_argument("--priority", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Archive an incomplete checkpoint and start from card 0",
    )


def _schedule_config(args: argparse.Namespace) -> BackfillConfig:
    defaults = config_from_settings()

    return BackfillConfig(
        batch_size=(
            args.batch_size if args.batch_size is not None else defaults.batch_size
        ),
        min_interval_minutes=(
            args.min_interval_minutes
            if args.min_interval_minutes is not None
            else defaults.min_interval_minutes
        ),
        max_interval_minutes=(
            args.max_interval_minutes
            if args.max_interval_minutes is not None
            else defaults.max_interval_minutes
        ),
        priority=args.priority if args.priority is not None else defaults.priority,
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="scraper")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("once", help="Process one eligible scrape job")
    subparsers.add_parser("worker", help="Continuously process scrape jobs")

    backfill = subparsers.add_parser(
        "backfill-missing",
        help="Schedule cards that do not have any card listing",
    )
    _add_schedule_arguments(
        backfill,
        default_state_path=scraper_settings.backfill_state_path,
    )

    refresh_all = subparsers.add_parser(
        "refresh-all",
        help="Schedule every card in the catalog for scraping",
    )
    _add_schedule_arguments(
        refresh_all,
        default_state_path=scraper_settings.refresh_all_state_path,
    )
    refresh_all.add_argument(
        "--include-disabled",
        action="store_true",
        help="Re-enable and schedule targets disabled after a 404",
    )

    reset = subparsers.add_parser(
        "reset-target", help="Re-enable a target disabled after a 404"
    )
    identifiers = reset.add_mutually_exclusive_group(required=True)
    identifiers.add_argument("--card-id", type=int)
    identifiers.add_argument("--ygo-id", type=int)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    if args.command == "once":
        asyncio.run(run_once())
    elif args.command == "worker":
        asyncio.run(run_worker())
    elif args.command == "reset-target":
        raise SystemExit(
            asyncio.run(_reset_target(card_id=args.card_id, ygo_id=args.ygo_id))
        )
    else:
        try:
            if args.command == "backfill-missing":
                result = asyncio.run(
                    run_missing_listings_backfill(
                        state_path=args.state_file,
                        config=_schedule_config(args),
                        restart=args.restart,
                        dry_run=args.dry_run,
                    )
                )
            else:
                result = asyncio.run(
                    run_full_catalog_refresh(
                        state_path=args.state_file,
                        config=_schedule_config(args),
                        include_disabled=args.include_disabled,
                        restart=args.restart,
                        dry_run=args.dry_run,
                    )
                )
        except (BackfillStateError, ValueError) as exc:
            parser.error(str(exc))

        print(json.dumps(asdict(result), sort_keys=True))


if __name__ == "__main__":
    main()
