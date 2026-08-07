import argparse
import asyncio

from .reindex import reindex_cards
from .worker import create_worker


async def _run(command: str, batch_size: int) -> None:
    worker = create_worker()
    try:
        if command == "once":
            await worker.process_once()
        elif command == "worker":
            await worker.run_forever()
        else:
            print(await reindex_cards(worker.search, batch_size=batch_size))
    finally:
        await worker.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="search-index")
    parser.add_argument("command", choices=["once", "worker", "reindex"])
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()
    asyncio.run(_run(args.command, args.batch_size))


if __name__ == "__main__":
    main()
