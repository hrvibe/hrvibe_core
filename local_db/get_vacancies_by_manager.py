#!/usr/bin/env python3
"""
Get vacancies by manager_id from database.

Usage:
  python3 local_db/get_vacancies_by_manager.py <manager_id>

Example:
  python3 local_db/get_vacancies_by_manager.py 7853115214
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

from database import SessionLocal, Vacancies  # noqa: E402
from sqlalchemy.inspection import inspect  # noqa: E402


def get_vacancies_by_manager_id(manager_id: str) -> Optional[list[Vacancies]]:
    """Get all vacancies for a given manager_id."""
    db = SessionLocal()
    try:
        vacancies = db.query(Vacancies).filter(Vacancies.manager_id == manager_id).all()

        if vacancies:
            print("=" * 60)
            print(f"✅ Found {len(vacancies)} vacancy(ies) for manager_id: {manager_id}")
            print("=" * 60)
            mapper = inspect(Vacancies)

            for vac in vacancies:
                print("-" * 60)
                for column in mapper.columns:
                    value = getattr(vac, column.key)
                    print(f"{column.key:28} {value}")
            return vacancies
        else:
            print(f"❌ No vacancies found for manager_id {manager_id}")
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
        print("Usage: python3 local_db/get_vacancies_by_manager.py <manager_id>")
        print("\nExample:")
        print("  python3 local_db/get_vacancies_by_manager.py 7853115214")
        sys.exit(1)

    manager_id = sys.argv[1]
    get_vacancies_by_manager_id(manager_id)


if __name__ == "__main__":
    main()

