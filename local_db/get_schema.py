#!/usr/bin/env python3
"""
Script to get database schema for hrbive_test
Usage: python3 local_db_setup/get_schema.py
"""

import os
import sys

# Add the project root to the path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Try to load .env file manually if dotenv not available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Fallback: load .env manually
    env_file = os.path.join(project_root, '.env')
    if os.path.exists(env_file):
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()

from database import engine, Base, Managers, Vacancies, Negotiations
from sqlalchemy import inspect

def get_schema():
    """Get and display database schema"""
    print("=" * 80)
    print("📊 Database Schema: hrbive_test")
    print("=" * 80)
    print()
    
    # Create inspector
    inspector = inspect(engine)
    
    # Get all table names
    tables = inspector.get_table_names()
    
    if not tables:
        print("⚠️  No tables found in database.")
        print("   Run the test script to create tables:")
        print("   python3 local_db_setup/test_database.py")
        print()
        print("=" * 80)
        print("📚 Expected Schema (from code models)")
        print("=" * 80)
        print()
        show_expected_schema()
        return
    
    print(f"📋 Found {len(tables)} table(s):")
    print()
    
    # Get schema for each table
    for table_name in tables:
        print("=" * 80)
        print(f"📐 Table: {table_name}")
        print("=" * 80)
        
        # Get columns
        columns = inspector.get_columns(table_name)
        
        print(f"\n{'Column Name':<30} {'Type':<25} {'Nullable':<10} {'Default':<20}")
        print("-" * 85)
        
        for column in columns:
            col_name = column['name']
            col_type = str(column['type'])
            nullable = "YES" if column['nullable'] else "NO"
            default = str(column['default']) if column['default'] is not None else ""
            
            print(f"{col_name:<30} {col_type:<25} {nullable:<10} {default:<20}")
        
        # Get primary keys
        pk_constraint = inspector.get_pk_constraint(table_name)
        if pk_constraint['constrained_columns']:
            print(f"\n🔑 Primary Key: {', '.join(pk_constraint['constrained_columns'])}")
        
        # Get foreign keys
        fks = inspector.get_foreign_keys(table_name)
        if fks:
            print(f"\n🔗 Foreign Keys:")
            for fk in fks:
                print(f"   {', '.join(fk['constrained_columns'])} → {fk['referred_table']}.{', '.join(fk['referred_columns'])}")
        
        # Get indexes
        indexes = inspector.get_indexes(table_name)
        if indexes:
            print(f"\n📇 Indexes:")
            for idx in indexes:
                unique = "UNIQUE" if idx['unique'] else ""
                print(f"   {idx['name']} {unique} ({', '.join(idx['column_names'])})")
        
        print()
    
    # Show model information
    print("=" * 80)
    print("📚 Model Information (from code)")
    print("=" * 80)
    print()
    show_expected_schema()

def show_expected_schema():
    """Show expected schema from code models"""
    models = [
        ("Managers", Managers, "managers"),
        ("Vacancies", Vacancies, "vacancies"),
        ("Negotiations", Negotiations, "negotiations")
    ]
    
    for model_name, model, table_name in models:
        print(f"📦 {model_name} (table: {table_name})")
        print("-" * 80)
        
        for col in model.__table__.columns:
            col_type = str(col.type)
            nullable = "NULL" if col.nullable else "NOT NULL"
            default = f"DEFAULT {col.default.arg}" if col.default else ""
            pk = "PRIMARY KEY" if col.primary_key else ""
            
            print(f"   {col.name:<30} {col_type:<25} {nullable:<10} {pk}")
        
        # Show foreign keys
        fks = []
        for fk in model.__table__.foreign_keys:
            fks.append(f"{fk.parent.name} → {fk.column.table.name}.{fk.column.name}")
        
        if fks:
            print(f"\n   Foreign Keys:")
            for fk in fks:
                print(f"      {fk}")
        
        print()

if __name__ == "__main__":
    try:
        get_schema()
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
