#!/usr/bin/env python3
"""
Test script for local database testing.
Run this to verify your database connection and tables are set up correctly.
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add the project root to the path (go up one directory from local_db_setup)
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from database import (
    init_db,
    SessionLocal,
    Managers,
    Vacancies,
    Negotiations
)


def test_database_connection():
    """Test if database connection works"""
    print("🔍 Testing database connection...")
    try:
        from database import engine
        with engine.connect() as conn:
            print("✅ Database connection successful!")
            return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False


def test_create_tables():
    """Test creating tables"""
    print("\n🔍 Creating tables...")
    try:
        init_db()
        print("✅ Tables created successfully!")
        return True
    except Exception as e:
        print(f"❌ Failed to create tables: {e}")
        return False


def cleanup_test_data(db):
    """Clean up existing test data before running tests"""
    try:
        # Delete in reverse dependency order to avoid foreign key violations
        # Delete resume first
        test_resume = db.query(Negotiations).filter(Negotiations.id == "test_resume_1").first()
        if test_resume:
            db.delete(test_resume)
            db.commit()
        
        # Delete vacancy
        test_vacancy = db.query(Vacancies).filter(Vacancies.id == "1").first()
        if test_vacancy:
            db.delete(test_vacancy)
            db.commit()
        
        # Delete manager
        test_manager = db.query(Managers).filter(Managers.id == "123456789").first()
        if test_manager:
            db.delete(test_manager)
            db.commit()
    except Exception as e:
        db.rollback()
        print(f"  ⚠️  Warning: Could not clean up existing test data: {e}")


def test_crud_operations():
    """Test Create, Read, Update, Delete operations"""
    print("\n🔍 Testing CRUD operations...")
    
    db = SessionLocal()
    try:
        # Clean up any existing test data first
        print("  Cleaning up existing test data...")
        cleanup_test_data(db)
        
        # Create a test manager
        print("  Creating test manager...")
        test_manager_id = "123456789"
        test_manager = Managers(
            id=test_manager_id,
            username="test_user",
            first_name="Test",
            last_name="User",
            privacy_policy_confirmed=True
        )
        db.add(test_manager)
        db.commit()
        print("  ✅ Manager created")
        
        # Read the manager
        print("  Reading manager...")
        manager = db.query(Managers).filter(Managers.id == test_manager_id).first()
        if manager:
            print(f"  ✅ Manager found: {manager.username}")
        else:
            print("  ❌ Manager not found")
            return False
        
        # Create a test vacancy
        print("  Creating test vacancy...")
        test_vacancy_id = "1"
        test_vacancy = Vacancies(
            id=test_vacancy_id,
            manager_id=test_manager_id,
            name="Test Vacancy",
            description_recieved=True,
        )
        db.add(test_vacancy)
        db.commit()
        print("  ✅ Vacancy created")
        
        # Create a test resume
        print("  Creating test resume...")
        test_resume = Negotiations(
            id="test_resume_1",
            vacancy_id=test_vacancy_id,
            applicant_first_name="John",
            applicant_last_name="Doe",
            applicant_email="john.doe@example.com",
        )
        db.add(test_resume)
        db.commit()
        print("  ✅ Resume created")
        
        # Read all records
        print("  Reading all records...")
        managers_count = db.query(Managers).count()
        vacancies_count = db.query(Vacancies).count()
        resumes_count = db.query(Negotiations).count()
        print(f"  ✅ Found {managers_count} managers, {vacancies_count} vacancies, {resumes_count} resumes")
        
        # Clean up test data (delete in reverse dependency order)
        print("  Cleaning up test data...")
        # Delete child records first (resume references vacancy and manager)
        db.delete(test_resume)
        db.commit()
        # Delete vacancy (references manager)
        db.delete(test_vacancy)
        db.commit()
        # Finally delete manager (no dependencies)
        db.delete(test_manager)
        db.commit()
        print("  ✅ Test data cleaned up")
        
        return True
        
    except Exception as e:
        db.rollback()
        print(f"  ❌ CRUD operations failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        db.close()


def main():
    print("=" * 50)
    print("DATABASE TESTING SCRIPT")
    print("=" * 50)
    
    # Check DATABASE_URL
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("\n❌ ERROR: DATABASE_URL not found in environment variables")
        print("\nFor SQLite (local testing):")
        print("  DATABASE_URL=sqlite:///./test.db")
        print("\nFor PostgreSQL (local):")
        print("  DATABASE_URL=postgresql://user:password@localhost:5432/dbname")
        return
    
    # Strip whitespace and special characters that might be accidentally included
    database_url = database_url.strip().rstrip('%')
    
    print(f"\n📊 Database URL: {database_url[:50]}..." if len(database_url) > 50 else f"\n📊 Database URL: {database_url}")
    
    # Run tests
    if not test_database_connection():
        return
    
    if not test_create_tables():
        return
    
    if not test_crud_operations():
        return
    
    print("\n" + "=" * 50)
    print("✅ ALL TESTS PASSED!")
    print("=" * 50)


if __name__ == "__main__":
    main()
