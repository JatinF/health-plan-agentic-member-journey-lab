"""Stdio entrypoint for the plan-guide MCP server."""

from membercare.cases import CaseStore
from membercare.catalog import load_catalog
from membercare.config import Settings
from membercare.mcp.servers import build_servers
from membercare.observe import Metrics
from membercare.services import Services


def main() -> None:
    settings = Settings.from_env()
    services = Services(load_catalog(settings.data_dir), CaseStore(settings.db_path), Metrics())
    build_servers(services)["plan"].run()


if __name__ == "__main__":
    main()
