"""
Script to setup the development environment for the project.
!!!!!!!!!!!!!!!!
To execute this script, run: 
source dev_setup.sh
!!!!!!!!!!!!!!!!
"""


#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="/Users/gridavyv/HRVibe/hrvibe_2.1"

cd "$PROJECT_ROOT"

echo "Activating virtual environment..."
source "$PROJECT_ROOT/venv/bin/activate"

echo "Installing Python dependencies..."
pip install -r "$PROJECT_ROOT/requirements.txt"

echo "Loading environment variables from .env (if present)..."
if [ -f "$PROJECT_ROOT/.env" ]; then
  set -a
  # shellcheck source=/Users/gridavyv/HRVibe/hrvibe_2.1/.env
  source "$PROJECT_ROOT/.env"
  set +a
else
  echo "Warning: .env file not found at $PROJECT_ROOT/.env"
fi

echo "Starting local PostgreSQL for testing..."
"$PROJECT_ROOT/local_db/start_postgres_for_testing.sh"

echo "Running database test script..."
python3 "$PROJECT_ROOT/local_db/test_database.py"

echo "Done."

