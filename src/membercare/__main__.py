"""Run the local member portal on loopback."""

import argparse
import logging

import uvicorn

from membercare import NOTICE
from membercare.api import create_app
from membercare.config import Settings


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Synthetic MemberCare AI lab")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    host = args.host or settings.host
    port = args.port or settings.port
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("membercare").info("%s host=%s port=%s", NOTICE, host, port)
    uvicorn.run(create_app(settings), host=host, port=port)


if __name__ == "__main__":
    main()
