import argparse
import asyncio
import logging

from .worker import run_once, run_worker


def main() -> None:
    parser = argparse.ArgumentParser(prog="scraper")
    parser.add_argument("command", choices=("once", "worker"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)

    if args.command == "once":
        asyncio.run(run_once())
    else:
        asyncio.run(run_worker())


if __name__ == "__main__":
    main()
