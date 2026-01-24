#!/bin/bash
# Quick setup script for local database testing

echo "🔧 Setting up local database for testing..."

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ .env file not found!"
    exit 1
fi

# Check if DATABASE_URL is set
if ! grep -q "DATABASE_URL" .env; then
    echo ""
    echo "📝 DATABASE_URL not found in .env file."
    echo ""
    echo "Choose an option:"
    echo "1) SQLite (simplest - no setup needed)"
    echo "2) PostgreSQL (matches production)"
    echo ""
    read -p "Enter choice (1 or 2): " choice
    
    if [ "$choice" == "1" ]; then
        echo "DATABASE_URL=sqlite:///./test.db" >> .env
        echo "✅ Added SQLite DATABASE_URL to .env"
    elif [ "$choice" == "2" ]; then
        echo ""
        echo "Enter PostgreSQL connection string:"
        echo "Format: postgresql://username:password@localhost:5432/dbname"
        read -p "DATABASE_URL: " db_url
        echo "DATABASE_URL=$db_url" >> .env
        echo "✅ Added PostgreSQL DATABASE_URL to .env"
    else
        echo "❌ Invalid choice"
        exit 1
    fi
fi

# Install dependencies
echo ""
echo "📦 Installing dependencies..."
pip3 install sqlalchemy python-dotenv

# Check if PostgreSQL is needed
if grep -q "postgresql://" .env; then
    echo "📦 Installing PostgreSQL driver..."
    pip3 install psycopg2-binary
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "Run the test script:"
echo "  python3 test_database.py"
