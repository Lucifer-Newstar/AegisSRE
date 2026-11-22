"""Schema fixture only. Never use this module as a server entrypoint."""

from api_gateway.config import Settings
from api_gateway.main import create_app

app = create_app(
    Settings(
        api_token="schema-fixture",
        incidents_token="schema-fixture",
        metadata_token="metadata-schema-fixture",
    )
)
