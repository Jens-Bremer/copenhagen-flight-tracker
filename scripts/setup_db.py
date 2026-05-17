import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from src.database import initialize_database
from src.migrations import apply_migrations

initialize_database(config.DATABASE_PATH)
applied = apply_migrations(config.DATABASE_PATH)
print(f"Database ready at {config.DATABASE_PATH}")
print(f"Applied {applied} migration(s)")
