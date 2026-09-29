from __future__ import annotations

import argparse
import logging
import os
import sys
import tempfile
from pathlib import Path

import uvicorn


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smart Navigation local API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    log_config = "default"
    if getattr(sys, "frozen", False):
        log_path = Path(tempfile.gettempdir()) / (
            f"smart-navigation-backend-{os.getpid()}.log"
        )
        logging.basicConfig(
            filename=log_path,
            level=logging.WARNING,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
            force=True,
        )
        log_config = None
    try:
        uvicorn.run(
            "backend.main:app",
            host=arguments.host,
            port=arguments.port,
            log_config=log_config,
            log_level="warning",
        )
    except Exception:
        logging.exception("Local backend failed")
        raise


if __name__ == "__main__":
    main()
