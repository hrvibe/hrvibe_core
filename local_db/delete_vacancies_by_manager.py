#!/usr/bin/env python3
"""
Delete Vacancies by manager_id from database
Usage: python3 local_db/delete_vacancies_by_manager.py <manager_id> [--confirm]
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add the project root to the path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from database import SessionLocal, Vacancies

def delete_vacancies_by_manager_id(manager_id, confirm=False):
    """Delete all vacancies for a given manager_id"""
    db = SessionLocal()
    
    try:
        # First, check if any vacancies exist for this manager
        vacancies = db.query(Vacancies).filter(Vacancies.manager_id == manager_id).all()
        
        if not vacancies:
            print(f"❌ No vacancies found for manager_id {manager_id}")
            return False
        
        # Display vacancies info before deletion
        print("=" * 60)
        print(f"⚠️  Vacancies to be deleted (Manager ID: {manager_id})")
        print(f"Found {len(vacancies)} vacancy/vacancies")
        print("=" * 60)
        
        for idx, vacancy in enumerate(vacancies, 1):
            print(f"\nVacancy #{idx}:")
            print(f"  ID:                          {vacancy.id}")
            print(f"  Name:                        {vacancy.name or 'N/A'}")
            print(f"  Manager ID:                  {vacancy.manager_id}")
            print(f"  Video Record Agreed:         {vacancy.video_record_agreed}")
            print(f"  Video Sending Confirmed:     {vacancy.video_sending_confirmed}")
            print(f"  Video Received:             {vacancy.video_received}")
            print(f"  Description Received:       {vacancy.description_recieved}")
            print(f"  Sourcing Criterias Received: {vacancy.sourcing_criterias_recieved}")
            print(f"  Negotiations Collection Received: {vacancy.negotiations_collection_recieved}")
            print(f"  Created At:                 {vacancy.created_at}")
            print(f"  Updated At:                 {vacancy.updated_at}")
        
        print("\n" + "=" * 60)
        
        # Confirm deletion
        if not confirm:
            response = input(f"\n⚠️  Are you sure you want to delete {len(vacancies)} vacancy/vacancies? (yes/no): ").strip().lower()
            if response not in ['yes', 'y']:
                print("❌ Deletion cancelled")
                return False
        
        # Delete all vacancies for this manager
        deleted_count = 0
        for vacancy in vacancies:
            db.delete(vacancy)
            deleted_count += 1
        
        db.commit()
        
        print(f"\n✅ Successfully deleted {deleted_count} vacancy/vacancies for manager_id {manager_id}")
        return True
            
    except Exception as e:
        db.rollback()
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 local_db/delete_vacancies_by_manager.py <manager_id> [--confirm]")
        print("\nOptions:")
        print("  <manager_id>    The ID of the manager whose vacancies to delete (string)")
        print("  --confirm       Skip confirmation prompt")
        print("\nExample:")
        print("  python3 local_db/delete_vacancies_by_manager.py 123456789")
        print("  python3 local_db/delete_vacancies_by_manager.py 123456789 --confirm")
        sys.exit(1)
    
    try:
        # Convert to string since Vacancies.manager_id is String type in database
        manager_id = str(sys.argv[1])
        confirm = '--confirm' in sys.argv
        
        success = delete_vacancies_by_manager_id(manager_id, confirm=confirm)
        sys.exit(0 if success else 1)
        
    except ValueError:
        print(f"❌ Error: '{sys.argv[1]}' is not a valid ID")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n❌ Deletion cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
