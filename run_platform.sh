#!/bin/bash
# run_platform.sh
# Bash script to automate virtual environment creation, dependency installation,
# check/seed database, and launch the interactive CLI advisor on macOS/Linux.

# Clear screen
clear
echo "=========================================================="
echo "    CCR Compliance Agent - Platform Setup & Launch Script "
echo "=========================================================="

# 1. Verify Python Installation
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 is not installed or not in your PATH. Please install Python to proceed."
    exit 1
fi

# 2. Initialize Virtual Environment
if [ ! -d "venv" ]; then
    echo -e "\n[1/4] Creating Python virtual environment ('venv')..."
    python3 -m venv venv
else
    echo -e "\n[1/4] Virtual environment 'venv' already exists. Skipping creation."
fi

# 3. Install Dependencies
echo -e "\n[2/4] Installing python packages and Playwright dependencies..."
./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt
./venv/bin/playwright install chromium

# 4. Copy Environment Variable Template
if [ ! -f ".env" ]; then
    echo -e "\n[3/4] Copying .env.example template to active .env config..."
    cp .env.example .env
fi

# 5. Check and seed database
echo -e "\n[3/4] Checking database status..."
if [ -d "output/chroma_db" ]; then
    echo "  Chroma DB already exists under output/chroma_db. Skipping crawler pre-seeding."
    echo "  (If you want to force-reseed, delete output/chroma_db and re-run this script.)"
else
    echo "  No existing database found. Initializing new database..."
    echo "Pre-seeding database with Title 8 regulations (3 safety sections)..."
    
    # Run Initial Pre-Seed Ingestion
    ./venv/bin/python load_vault.py --url https://www.dir.ca.gov/title8/3204.html --limit 10
    ./venv/bin/python load_vault.py --url https://www.dir.ca.gov/title8/3203.html --limit 10
    ./venv/bin/python load_vault.py --url https://www.dir.ca.gov/title8/3395.html --limit 10
fi

# 6. Start CLI Advisor
echo -e "\n[4/4] Starting the interactive Compliance Advisor CLI..."
sleep 1
./venv/bin/python agent_cli.py chat
