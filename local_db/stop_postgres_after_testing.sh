#!/bin/bash
# Script to stop PostgreSQL service after testing is done
# Usage: ./stop_postgres_after_testing.sh

set -e  # Exit on error

PG_VERSION="postgresql@15"

echo "=" | tr -d '\n'
echo "🛑 Stopping PostgreSQL After Testing"
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
    exit 1
fi
echo ""

# Step 2: Check if PostgreSQL is running
echo "🔍 Step 2: Checking PostgreSQL service status..."
if brew services list | grep -q "$PG_VERSION.*started"; then
    echo "✅ PostgreSQL service is running"
    echo ""
    
    # Step 3: Stop PostgreSQL service
    echo "🔍 Step 3: Stopping PostgreSQL service..."
    brew services stop $PG_VERSION
    echo "   ⏳ Waiting for PostgreSQL to stop..."
    sleep 3
    
    # Verify it's stopped
    if brew services list | grep -q "$PG_VERSION.*started"; then
        echo "⚠️  PostgreSQL service might still be stopping..."
        echo "   Check status with: brew services list | grep postgresql"
    else
        echo "✅ PostgreSQL service stopped successfully"
    fi
else
    echo "ℹ️  PostgreSQL service is not running"
    echo "   Nothing to stop"
fi
echo ""

# Summary
echo "=" | tr -d '\n'
echo "✅ PostgreSQL has been stopped"
echo "=" | tr -d '\n'
echo ""
echo "💡 To start PostgreSQL again:"
echo "   ./local_db_setup/start_postgres_for_testing.sh"
echo ""
echo "💡 Check service status:"
echo "   brew services list | grep postgresql"
