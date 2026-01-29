#!/usr/bin/env python3
"""
Get negotiations by resume_id from database.

Usage:
  python3 local_db/get_negotiations_by_resume.py <resume_id>

Example:
  python3 local_db/get_negotiations_by_resume.py resume_123456
"""

import os
import sys
from typing import List
from pathlib import Path

from dotenv import load_dotenv

# Add the project root to the path first
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Load environment variables from .env file in project root
env_path = Path(project_root) / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    # Try loading from current directory as fallback
    load_dotenv()
    # If still no .env file, warn the user
    if not os.getenv("DATABASE_URL"):
        print("⚠️  Warning: .env file not found. Make sure environment variables are set.")
        print(f"   Expected .env file at: {env_path}")
        print("   Required variables: DATABASE_URL (and others for full functionality)")
        sys.exit(1)

from shared_services.database import SessionLocal, Negotiations  # noqa: E402
from sqlalchemy.inspection import inspect  # noqa: E402


def get_negotiations_by_resume_id(resume_id: str) -> List[Negotiations]:
    """Get all negotiation records by resume_id."""
    db = SessionLocal()
    try:
        negotiations = db.query(Negotiations).filter(Negotiations.resume_id == resume_id).all()

        if negotiations:
            print("=" * 60)
            print(f"✅ Found {len(negotiations)} negotiation(s) with resume_id: {resume_id}")
            print("=" * 60)
            mapper = inspect(Negotiations)

            for idx, negotiation in enumerate(negotiations, 1):
                print(f"\n--- Negotiation #{idx} ---")
                print("-" * 60)
                for column in mapper.columns:
                    value = getattr(negotiation, column.key)
                    print(f"{column.key:28} {value}")
            return negotiations
        else:
            print(f"❌ No negotiations found with resume_id {resume_id}")
            return []

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return []
    finally:
        db.close()


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 local_db/get_negotiations_by_resume.py <resume_id>")
        print("\nExample:")
        print("  python3 local_db/get_negotiations_by_resume.py resume_123456")
        sys.exit(1)

    resume_id = sys.argv[1]
    get_negotiations_by_resume_id(resume_id)


if __name__ == "__main__":
    main()
