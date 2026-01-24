#!/bin/bash
# Script to start PostgreSQL service and create test database before testing
# Usage: ./start_postgres_for_testing.sh

set -e  # Exit on error

DB_NAME="hrbive_test"
PG_VERSION="postgresql@15"

echo "=" | tr -d '\n'
echo "🚀 Starting PostgreSQL for Testing"
echo "=" | tr -d '\n'
echo ""

# Step 1: Check PostgreSQL installation
echo "🔍 Step 1: Checking PostgreSQL installation..."
if brew list $PG_VERSION &>/dev/null; then
    echo "✅ PostgreSQL@15 found"
elif brew list postgresql@14 &>/dev/null; then
    echo "✅ PostgreSQL@14 found"
    PG_VERSION="postgresql@14"
elif brew list postgresql &>/dev/null; then
    echo "✅ PostgreSQL found"
    PG_VERSION="postgresql"
else
    echo "❌ PostgreSQL not installed"
    echo ""
    echo "To install PostgreSQL, run:"
    echo "  brew install postgresql@15"
    exit 1
fi

# Get PostgreSQL bin directory
PG_BIN_DIR=$(brew --prefix $PG_VERSION)/bin
if [ ! -d "$PG_BIN_DIR" ]; then
    echo "❌ Could not find PostgreSQL bin directory"
    exit 1
fi

echo "   PostgreSQL binaries: $PG_BIN_DIR"
echo ""

# Step 2: Start PostgreSQL service
echo "🔍 Step 2: Starting PostgreSQL service..."
if brew services list | grep -q "$PG_VERSION.*started"; then
    echo "✅ PostgreSQL service is already running"
else
    echo "   Starting PostgreSQL service..."
    brew services start $PG_VERSION
    echo "   ⏳ Waiting for PostgreSQL to start..."
    sleep 5
    
    # Verify it's running
    PG_ISREADY="$PG_BIN_DIR/pg_isready"
    if [ -f "$PG_ISREADY" ]; then
        if $PG_ISREADY -q; then
            echo "✅ PostgreSQL service started successfully"
        else
            echo "⚠️  PostgreSQL service started but connection check failed"
            echo "   It might still be initializing. Continuing anyway..."
        fi
    else
        if brew services list | grep -q "$PG_VERSION.*started"; then
            echo "✅ PostgreSQL service started"
        else
            echo "❌ Failed to start PostgreSQL service"
            exit 1
        fi
    fi
fi
echo ""

# Step 3: Check if test database exists
echo "🔍 Step 3: Checking test database..."
PSQL="$PG_BIN_DIR/psql"
CREATEDB="$PG_BIN_DIR/createdb"

if $PSQL -lqt | cut -d \| -f 1 | grep -qw "$DB_NAME"; then
    echo "✅ Test database '$DB_NAME' already exists"
else
    echo "   Creating test database '$DB_NAME'..."
    if $CREATEDB "$DB_NAME"; then
        echo "✅ Test database '$DB_NAME' created successfully"
    else
        echo "❌ Failed to create test database"
        exit 1
    fi
fi
echo ""

# Step 4: Verify database connection
echo "🔍 Step 4: Verifying database connection..."
if $PSQL -d "$DB_NAME" -c "SELECT 1;" &>/dev/null; then
    echo "✅ Database connection successful"
else
    echo "⚠️  Could not verify database connection"
fi
echo ""

# Summary
echo "=" | tr -d '\n'
echo "✅ PostgreSQL is ready for testing!"
echo "=" | tr -d '\n'
echo ""
echo "📊 Status:"
echo "   PostgreSQL service: Running"
echo "   Test database: $DB_NAME"
echo ""
echo "💡 Next steps:"
echo "   1. Run your tests: python3 local_db_setup/test_database.py"
echo "   2. When done, stop PostgreSQL: ./local_db_setup/stop_postgres_after_testing.sh"
echo ""
echo "💡 Useful commands:"
echo "   Connect to DB: $PSQL -d $DB_NAME"
echo "   List databases: $PSQL -l"
echo "   Check service: brew services list | grep postgresql"
