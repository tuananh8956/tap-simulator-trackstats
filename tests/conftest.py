import os
import tempfile
import pytest
from pathlib import Path

# Set environment variable before importing any app modules
test_db_file = os.path.join(tempfile.mkdtemp(), "isolated_test_trackstats.db")
os.environ["TRACKSTATS_DB_PATH"] = test_db_file

from src.main import app, session_manager, db

@pytest.fixture(autouse=True)
def clean_test_db():
    db.init_db()
    yield db
