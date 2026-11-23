from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from membercare.api import create_app
from membercare.catalog import default_data_dir
from membercare.config import Settings, repo_root


@pytest.fixture
def client(tmp_path: Path):
    settings = Settings(
        data_dir=default_data_dir(),
        db_path=tmp_path / "lab.db",
        checkpoint_path=tmp_path / "checkpoints.sqlite",
        web_dir=repo_root() / "web",
    )
    with TestClient(create_app(settings)) as test_client:
        test_client.db_path = settings.db_path
        test_client.checkpoint_path = settings.checkpoint_path
        yield test_client


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
