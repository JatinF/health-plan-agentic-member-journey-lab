"""Paths for the checkout. Local runs bind to loopback."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    checkpoint_path: Path
    web_dir: Path
    host: str = "127.0.0.1"
    port: int = 8765

    @staticmethod
    def from_env() -> "Settings":
        package_data = Path(__file__).resolve().parent / "data"
        root = repo_root()
        var_dir = Path(os.environ.get("MEMBERCARE_VAR", root / "var"))
        return Settings(
            data_dir=Path(os.environ.get("MEMBERCARE_DATA", package_data)),
            db_path=Path(os.environ.get("MEMBERCARE_DB", var_dir / "membercare.db")),
            checkpoint_path=Path(os.environ.get("MEMBERCARE_CHECKPOINT", var_dir / "checkpoints.sqlite")),
            web_dir=Path(os.environ.get("MEMBERCARE_WEB", root / "web")),
            host=os.environ.get("MEMBERCARE_HOST", "127.0.0.1"),
            port=int(os.environ.get("MEMBERCARE_PORT", "8765")),
        )
