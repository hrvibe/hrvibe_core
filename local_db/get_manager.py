#!/usr/bin/env python3
"""
Get Manager by ID from database
Usage: python3 local_db/get_manager.py <manager_id>
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add the project root to the path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from database import SessionLocal, Managers
from sqlalchemy.inspection import inspect

def get_manager_by_id(manager_id):
    """Get manager by ID"""
    db = SessionLocal()
    
    try:
        manager = db.query(Managers).filter(Managers.id == manager_id).first()
        
        if manager:
            print("=" * 60)
            print(f"✅ Found Manager (ID: {manager_id})")
            print("=" * 60)

            mapper = inspect(Managers)
            for column in mapper.columns:
                value = getattr(manager, column.key)
                print(f"{column.key:28} {value}")

            return manager
        else:
            print(f"❌ Manager with ID {manager_id} not found")
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
        print("Usage: python3 local_db/get_manager.py <manager_id>")
        print("\nExample:")
        print("  python3 local_db/get_manager.py 123456789")
        sys.exit(1)

    manager_id = sys.argv[1]
    get_manager_by_id(manager_id)

if __name__ == "__main__":
    main()
