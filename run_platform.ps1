# run_platform.ps1
# PowerShell script to automate virtual environment creation, dependency installation,
# initial database seeding using load_vault.py, and launching the interactive CLI advisor.

Clear-Host
Write-Output "=========================================================="
Write-Output "    CCR Compliance Agent - Platform Setup & Launch Script "
Write-Output "=========================================================="

# 1. Verify Python Installation
if (!(Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python is not installed or not in your PATH. Please install Python to proceed."
    Exit
}

# 2. Initialize Virtual Environment
if (!(Test-Path "venv")) {
    Write-Output "`n[1/4] Creating Python virtual environment ('venv')..."
    python -m venv venv
} else {
    Write-Output "`n[1/4] Virtual environment 'venv' already exists. Skipping creation."
}

# 3. Install Dependencies
Write-Output "`n[2/4] Installing python packages and Playwright dependencies..."
& .\venv\Scripts\pip.exe install --upgrade pip
& .\venv\Scripts\pip.exe install -r requirements.txt
& .\venv\Scripts\playwright.exe install chromium

# 4. Copy Environment Variable Template & Prompt for Keys
if (!(Test-Path ".env")) {
    Write-Output "`n[3/4] Copying .env.example template to active .env config..."
    Copy-Item .env.example .env
}

# 5. Check and seed database
Write-Output "`n[3/4] Checking database status..."
$dbExists = Test-Path "output/chroma_db"

if ($dbExists) {
    Write-Output "  Chroma DB already exists under output/chroma_db. Skipping crawler pre-seeding."
    Write-Output "  (If you want to force-reseed, delete output/chroma_db and re-run this script.)"
} else {
    Write-Output "  No existing database found. Initializing new database..."
    
    # Run Initial Pre-Seed Ingestion
    Write-Output "Pre-seeding database with Title 8 regulations (3 safety sections)..."
    try {
        # Ingest Section 3204 (Medical Record Access)
        Write-Output "Ingesting Section 3204 (Access to Employee Exposure and Medical Records)..."
        & .\venv\Scripts\python.exe load_vault.py --url https://www.dir.ca.gov/title8/3204.html --limit 10
        
        # Ingest Section 3203 (IIPP)
        Write-Output "Ingesting Section 3203 (Injury and Illness Prevention Program)..."
        & .\venv\Scripts\python.exe load_vault.py --url https://www.dir.ca.gov/title8/3203.html --limit 10

        # Ingest Section 3395 (Heat Illness Prevention)
        Write-Output "Ingesting Section 3395 (Heat Illness Prevention)..."
        & .\venv\Scripts\python.exe load_vault.py --url https://www.dir.ca.gov/title8/3395.html --limit 10
    } catch {
        Write-Warning "Initial ingestion pre-seed encountered issues: $_"
    }
}

# 6. Start CLI Advisor
Write-Output "`n[4/4] Starting the interactive Compliance Advisor CLI..."
Start-Sleep -Seconds 1
& .\venv\Scripts\python.exe agent_cli.py chat

