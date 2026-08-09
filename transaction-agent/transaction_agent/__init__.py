"""Transaction Agent: natural-language payment requests -> structured, human-approved, simulated transactions."""

from dotenv import load_dotenv as _load_dotenv

# Loaded here, not in each front end: several submodules (audit.py,
# recipient_directory.py, users.py) compute a DEFAULT_*_PATH constant from
# os.environ at *import time*, to auto-select Postgres when DATABASE_URL is
# set. That only works if .env is loaded before this package's submodules
# are imported — guaranteed here, but not if a front end called
# load_dotenv() after its `from transaction_agent... import ...` lines.
_load_dotenv()
