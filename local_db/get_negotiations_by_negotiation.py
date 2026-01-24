#!/usr/bin/env python3
"""
Get negotiation by id from database.

Usage:
  python3 local_db/get_negotiations_by_vacancy.py <negotiation_id>

Example:
  python3 local_db/get_negotiations_by_vacancy.py 4937619236
"""

import os
import sys
from typing import Optional

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add the project root to the path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from database import SessionLocal, Negotiations  # noqa: E402
from sqlalchemy.inspection import inspect  # noqa: E402


def get_negotiation_by_id(negotiation_id: str) -> Optional[Negotiations]:
    """Get a negotiation record by its unique id."""
    db = SessionLocal()
    try:
        negotiation = db.query(Negotiations).filter(Negotiations.id == negotiation_id).first()

        if negotiation:
            print("=" * 60)
            print(f"✅ Found negotiation with id: {negotiation_id}")
            print("=" * 60)
            mapper = inspect(Negotiations)

            print("-" * 60)
            for column in mapper.columns:
                value = getattr(negotiation, column.key)
                print(f"{column.key:28} {value}")
            return negotiation
        else:
            print(f"❌ No negotiation found with id {negotiation_id}")
            return None

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback

        traceback.print_exc()
        return None
    finally:
        db.close()


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 local_db/get_negotiations_by_vacancy.py <negotiation_id>")
        print("\nExample:")
        print("  python3 local_db/get_negotiations_by_vacancy.py 4937619236")
        sys.exit(1)

    negotiation_id = sys.argv[1]
    get_negotiation_by_id(negotiation_id)


if __name__ == "__main__":
    main()
