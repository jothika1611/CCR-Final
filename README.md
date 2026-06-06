# California Code of Regulations (CCR) Compliance Platform

An AI-powered regulatory advisor designed to crawl, parse, index, and query the **California Code of Regulations (CCR)**. The platform runs a local ONNX embedding generator, a serverless in-process **Chroma Vector Database**, and calls the **Groq API** to provide Retrieval-Augmented Generation (RAG) compliance roadmaps for California facility operators.

This version features a **premium terminal-based Interactive CLI** that supports rich colors, structured tables, markdown rendering, and automatic API key configuration loops.

---

## 🏗️ System Architecture & Data Flow

```
[Seed URL] ──(Stage 1: Link Discovery)──> [output/url_manifest.json]
                                                  │
                                         (Stage 2: Ingestion) <── [output/ingestion_state.json]
                                                  │                (Resume checkpoints)
                                                  ▼
                                       [BeautifulSoup Parser]
                                                  │
                          ┌───────────────────────┴───────────────────────┐
                          ▼                                               ▼
          [output/ccr_vault.jsonl]                             [Local Embedder: ONNX BGE]
          (Structured local archive)                                      │
                                                                          ▼
                                                                  [Chroma Vector DB]
                                                                  (In-Process, SQLite-backed)
```

---

## 📂 Codebase Structure

```
CCR-project/
├── run_platform.ps1        # PowerShell script automating environment setup & demo seeding
├── requirements.txt         # Package dependencies (ChromaDB, FastEmbed, Crawl4AI, Rich)
├── .env.example             # Configuration template
├── .env                     # Active environment variables (git-ignored)
├── load_vault.py            # Recursive two-stage ingestion and database indexing pipeline
├── agent_cli.py             # Interactive CLI chatbot, sandbox lookup, and status diagnostics
└── calregs_agent/           # Core Source Code Package
    ├── config.py            # Pydantic Settings configuration manager
    └── core/
        ├── scraper.py       # Scraper engine (Crawl4AI DOM parsing & HTTP fallbacks)
        ├── embeddings.py    # Local FastEmbed service (BGE model)
        ├── vector_db.py     # Local ChromaDB connection & similarity search
        └── models.py        # Pydantic schema validation (CCRSection, SearchHit)
```

---

## ⚙️ Setup & Operations

### Pre-seeded Database (Instant Run)
To make local evaluation as simple as possible, the database located under `output/chroma_db` is **pre-seeded** and included directly in this repository. Evaluation reviewers do not need to run the crawler or seed the database themselves to test the advisor; it is ready to run out of the box!

### Method 1: Automatic Setup & Run (Recommended)

#### On Windows (PowerShell):
Open PowerShell (As Administrator) in the repository root and execute:
```powershell
Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process
.\run_platform.ps1
```

#### On macOS / Linux (Bash):
Open a terminal in the repository root and execute:
```bash
chmod +x run_platform.sh
./run_platform.sh
```

These scripts will automatically:
1. Create a virtual environment (`venv`).
2. Install pip requirements and Playwright/Chromium dependencies.
3. Verify if `output/chroma_db` is present (skipping crawling if found, or automatically seeding it with key sections of Title 8 safety guidelines if not).
4. Launch the **Interactive Compliance Chat CLI** directly.


### Method 2: Manual Step-by-Step Execution

1. **Initialize Environment & Install Packages**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: .\venv\Scripts\activate
   pip install -r requirements.txt
   playwright install chromium
   ```

2. **Configure Environment Variables**:
   Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
   Add your `GROQ_API_KEY` (if left blank, the CLI will prompt you to enter it dynamically on start and offer to save it).

3. **Run Ingestion & Seeding**:
   Crawl and index regulations from a seed URL (e.g. Title 8 index):
   ```bash
   python load_vault.py --url https://www.dir.ca.gov/title8/3204.html --limit 5
   ```
   * *Stage 1 (Discovery)* outputs the target links to `output/url_manifest.json`.
   * *Stage 2 (Indexing)* processes targets, respects checkpoints in `output/ingestion_state.json` (allowing crashes/resumes), and commits vectors into Chroma.

4. **Launch the Compliance Advisor Chat**:
   ```bash
   python agent_cli.py chat
   ```

5. **Execute a Semantic Search Sandbox Lookup**:
   Check raw vector hits and cosine similarity scores:
   ```bash
   python agent_cli.py lookup --query "employee injury program" --limit 3
   ```

6. **Display System Health Dashboard**:
   ```bash
   python agent_cli.py status
   ```

---

## ⚡ Design Decisions & Core Rubric Adherence

1. **Serverless ChromaDB (Local SQLite-backed)**:
   Migrating the database to ChromaDB allows the entire RAG pipeline to run in-process without requiring Docker, background containers, or external cloud accounts. This makes evaluation robust and zero-dependency for reviewers.
2. **Two-Stage Ingestion Resiliency**:
   Discovery (Stage 1) is isolated from Ingestion (Stage 2). The checkpoints database ensures that if the crawler rate-limits or times out, restarting immediately skips success nodes and resumes the queue.
3. **Link & Asset Filtering**:
   Link discovery explicitly excludes CSS, JS, images, and other non-HTML extensions to prevent crawling waste, while normalizing URL paths to avoid duplicate case visits.
4. **FastEmbed CPU Vectorization**:
   We generate embeddings locally using ONNX `BAAI/bge-small-en-v1.5`, which takes only milliseconds on a CPU and costs zero API credits.
5. **Key Key Prompting**:
   If no Groq key is found in the environment, the CLI prompts the user to enter it securely and offers to persist it to `.env` for convenience, along with an interactive menu of recommended models.
