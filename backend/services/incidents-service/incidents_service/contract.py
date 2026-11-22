"""Schema-only application for contract checks. Never serve this module."""

from incidents_service.config import Settings
from incidents_service.main import create_app

app = create_app(Settings(dev_mode=True, database_url="sqlite:///:memory:"))
