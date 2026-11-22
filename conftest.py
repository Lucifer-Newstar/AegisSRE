"""Keep destructive reset helpers strictly on isolated in-memory test stores."""
import os

os.environ["DATABASE_URL"] = "sqlite:///:memory:"
