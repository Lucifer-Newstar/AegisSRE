"""Keep destructive reset helpers strictly on isolated in-memory test stores."""
import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

# Unit suites are explicitly local, not a production metadata launch.
os.environ["AEGIS_METADATA_DEV_MODE"] = "true"
