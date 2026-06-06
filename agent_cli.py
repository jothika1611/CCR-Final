#!/usr/bin/env python
import os
import sys
import json
import logging
import httpx
import argparse
import asyncio
from typing import List, Dict, Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich.prompt import Prompt, Confirm

# Resolve path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from calregs_agent.config import settings
from calregs_agent.core.embeddings import FastEmbedService
from calregs_agent.core.vector_db import ChromaStoreManager

console = Console()

# Set logging to warning only for CLI clean output
logging.getLogger("calregs_agent").setLevel(logging.WARNING)
logging.getLogger("chromadb").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

SUGGESTED_MODELS = [
    "llama-3.1-8b-instant",
    "llama-3.3-70b-specdec",
    "mixtral-8x7b-32768",
    "llama-3.2-3b-preview"
]

def print_welcome_banner():
    console.clear()
    banner = """
 ██████╗ ██████╗██████╗      ██████╗ ██████╗ ███╗   ███╗██████╗ ██╗     ██╗ ██████╗ ██████╗███████╗
██╔════╝██╔════╝██╔══██╗    ██╔════╝██╔═══██╗████╗ ████║██╔══██╗██║     ██║██╔════╝██╔════╝██╔════╝
██║     ██║     ██████╔╝    ██║     ██║   ██║██╔████╔██║██████╔╝██║     ██║███████╗██║     █████╗  
██║     ██║     ██╔══██╗    ██║     ██║   ██║██║╚██╔╝██║██╔═══╝ ██║     ██║██╔═══██╗██║     ██╔══╝  
╚██████╗╚██████╗██║  ██║    ╚██████╗╚██████╔╝██║ ╚═╝ ██║██║     ███████╗██║╚██████╔╝╚██████╗███████╗
 ╚═════╝ ╚═════╝╚═╝  ╚═╝     ╚═════╝ ╚═════╝ ╚═╝     ╚═╝╚═╝     ╚══════╝╚═╝ ╚═════╝  ╚═════╝╚══════╝
                                    California Code of Regulations
    """
    console.print(Panel(banner, style="bold green", subtitle="AI Compliance Advisor CLI v2.0", subtitle_align="right"))

def get_or_prompt_api_config():
    """
    Verifies if Groq API keys and models are active. If not, prompts the user.
    """
    api_key = os.environ.get("GROQ_API_KEY") or settings.groq_api_key
    model = os.environ.get("GROQ_MODEL") or settings.groq_model
    
    # Prompt for GROQ key if missing
    if not api_key:
        console.print(Panel.warning(
            "GROQ_API_KEY is not configured in your environment or .env file.\n"
            "An API key is required to query the LLM for regulatory compliance advice.",
            title="API Key Required"
        ))
        api_key = Prompt.ask("[bold yellow]Please enter your GROQ API Key[/bold yellow]", password=True)
        
        # Optionally persist key to .env
        save_env = Confirm.ask("Would you like to save this key to your local .env file?", default=True)
        if save_env:
            try:
                env_path = ".env"
                lines = []
                if os.path.exists(env_path):
                    with open(env_path, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                
                # Update or append
                key_updated = False
                for i, line in enumerate(lines):
                    if line.strip().startswith("GROQ_API_KEY="):
                        lines[i] = f"GROQ_API_KEY={api_key}\n"
                        key_updated = True
                        break
                
                if not key_updated:
                    lines.append(f"\nGROQ_API_KEY={api_key}\n")
                
                with open(env_path, "w", encoding="utf-8") as f:
                    f.writelines(lines)
                console.print("[green]✓ Key successfully persisted to .env[/green]")
            except Exception as e:
                console.print(f"[red]Could not save key to .env: {e}[/red]")

    # Prompt for model selection
    console.print("\n[bold green]Choose a Groq LLM model:[/bold green]")
    for idx, m in enumerate(SUGGESTED_MODELS):
        console.print(f" [bold cyan]{idx + 1}[/bold cyan] -> {m} " + ("[dim](default)[/dim]" if m == model else ""))
    
    choice = Prompt.ask(
        "[bold yellow]Select model number or type a custom model name[/bold yellow]", 
        default=str(SUGGESTED_MODELS.index(model) + 1 if model in SUGGESTED_MODELS else 1)
    )
    
    if choice.isdigit() and 1 <= int(choice) <= len(SUGGESTED_MODELS):
        selected_model = SUGGESTED_MODELS[int(choice) - 1]
    else:
        selected_model = choice

    console.print(f"[green]✓ Configured session with model: [bold]{selected_model}[/bold][/green]\n")
    return api_key, selected_model

async def get_agent_response(question: str, api_key: str, model: str, db: ChromaStoreManager, embedder: FastEmbedService) -> Dict[str, Any]:
    """
    RAG engine: embeds query, retrieves Chroma blocks, constructs prompt, calls Groq API.
    """
    legal_disclaimer = "Disclaimer: The guidance provided below is for educational purposes only and does not constitute official legal advice."
    
    # 1. Embed query
    query_vector = embedder.vectorize_single(question)
    
    # 2. Search local database
    matches = await db.query_vector_store(query_vector=query_vector, limit=3)
    if not matches:
        return {
            "answer": "I could not find any relevant regulations in my database to evaluate your question.",
            "citations": [],
            "disclaimer": legal_disclaimer
        }
        
    citations = [{"citation": m.section.citation or f"Section {m.section.section_number}", "url": m.section.source_url} for m in matches]
    
    # 3. Assemble context
    context_parts = []
    for m in matches:
        ref_name = m.section.citation or f"Section {m.section.section_number}"
        text_body = m.section.content_markdown
        if len(text_body) > 6000:
            text_body = text_body[:6000] + "\n... [Content truncated for token limits] ..."
        context_parts.append(
            f"Source Link: {m.section.source_url}\n"
            f"Citation Reference: {ref_name}\n"
            f"Markdown Content:\n{text_body}"
        )
    context_string = "\n\n---\n\n".join(context_parts)
    
    system_prompt = f"""You are a California Code of Regulations (CCR) Compliance Advisor.
Your objective is to provide clear, actionable advice to facility operators by evaluating their question against the retrieved regulatory context.

Question: {question}

Retrieved Context Documents:
{context_string}

Response Instructions:
1. Formulate your answer based ONLY on the provided context document facts. Do NOT refer to external materials or invent facts.
2. Provide a clear "Applicability Rationale" for why each regulation cited applies to the operator's business.
3. Structure your response clearly using markdown headings, lists, and spacing.
4. Reference the official citation tags (e.g. 8 CCR § 3204) directly in your paragraphs.
5. If the details provided in the query are insufficient to form a complete compliance mapping, specify 1 or 2 relevant follow-up questions at the very end under a "Clarifying Follow-up Questions" header.
6. Crucial: End your response by printing this exact disclaimer verbatim: "{legal_disclaimer}"
"""

    # 4. Invoke LLM
    groq_endpoint = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": system_prompt}],
        "temperature": 0.15
    }
    
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(groq_endpoint, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            completion_text = data["choices"][0]["message"]["content"]
            
        return {
            "answer": completion_text,
            "citations": citations,
            "disclaimer": legal_disclaimer
        }
    except Exception as err:
        return {
            "answer": f"[red]Error communicating with Groq API: {err}[/red]",
            "citations": citations,
            "disclaimer": legal_disclaimer
        }

async def run_chat():
    print_welcome_banner()
    
    # Pre-warm database & embeddings
    embedder = FastEmbedService()
    db = ChromaStoreManager(embed_service=embedder)
    
    if not db.check_connection():
        console.print("[bold red]❌ Error: Cannot establish database connection.[/bold red]")
        sys.exit(1)
        
    api_key, model = get_or_prompt_api_config()
    
    console.print(Panel(
        "Type your regulatory query below (e.g. 'What records must be kept for exposure?')\n"
        "Type [bold red]exit[/bold red] or [bold red]quit[/bold red] to end the session.",
        title="Interactive Advisor Chat Active",
        style="dim green"
    ))
    
    while True:
        try:
            question = Prompt.ask("\n[bold cyan]Operator[/bold cyan]")
            if question.strip().lower() in ("exit", "quit"):
                console.print("[yellow]Advisor session terminated. Good bye![/yellow]")
                break
                
            if not question.strip():
                continue
                
            with console.status("[bold green]Advisor is searching regulations & thinking...[/bold green]"):
                res = await get_agent_response(question, api_key, model, db, embedder)
            
            # Print Answer
            console.print("\n[bold green]CCR Advisor Response:[/bold green]")
            console.print(Markdown(res["answer"]))
            
            # Print Citations
            if res["citations"]:
                table = Table(title="Sources & Citations Cited", show_header=True, header_style="bold green")
                table.add_column("Citation", style="bold cyan")
                table.add_column("Source URL", style="dim underline")
                for c in res["citations"]:
                    table.add_row(c["citation"], c["url"])
                console.print("\n")
                console.print(table)
                
        except KeyboardInterrupt:
            console.print("\n[yellow]Advisor session terminated. Good bye![/yellow]")
            break

async def run_lookup(query: str, limit: int):
    embedder = FastEmbedService()
    db = ChromaStoreManager(embed_service=embedder)
    
    if not db.check_connection():
        console.print("[bold red]❌ Database offline.[/bold red]")
        return
        
    query_vector = embedder.vectorize_single(query)
    hits = await db.query_vector_store(query_vector, limit=limit)
    
    table = Table(title=f"Semantic Matches for: '{query}'", show_header=True, header_style="bold green")
    table.add_column("No.", style="bold cyan")
    table.add_column("Citation", style="bold yellow")
    table.add_column("Section Heading", style="bold white")
    table.add_column("Similarity Score", style="magenta")
    table.add_column("URL", style="dim underline")
    
    for idx, hit in enumerate(hits):
        table.add_row(
            str(idx+1),
            hit.section.citation or f"Section {hit.section.section_number}",
            hit.section.section_heading or "No Heading",
            f"{hit.score * 100:.1f}%",
            hit.section.source_url
        )
    console.print(table)

def run_status():
    embedder = FastEmbedService()
    db = ChromaStoreManager(embed_service=embedder)
    
    table = Table(title="System Status Dashboard", show_header=False)
    table.add_column("Property", style="bold cyan")
    table.add_column("Value", style="white")
    
    db_connected = db.check_connection()
    table.add_row("Database Status", "[green]Online[/green]" if db_connected else "[red]Offline[/red]")
    table.add_row("Chroma Storage Path", settings.chroma_db_path)
    table.add_row("Active Collection", settings.chroma_collection)
    table.add_row("Indexed Sections Count", str(db.count_points()))
    table.add_row("ONNX Embedding Model", settings.embedding_model)
    table.add_row("Environment Mode", settings.env)
    
    console.print(Panel(table, title="System Diagnostic", expand=False))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CCR Compliance Advisor CLI Panel")
    subparsers = parser.add_subparsers(dest="command", help="Available sub-commands")
    
    # Chat subparser
    subparsers.add_parser("chat", help="Start the interactive RAG consultation chat shell")
    
    # Lookup subparser
    lookup_parser = subparsers.add_parser("lookup", help="Execute a semantic similarity lookup query against Chroma")
    lookup_parser.add_argument("--query", type=str, required=True, help="The semantic query string")
    lookup_parser.add_argument("--limit", type=int, default=5, help="Max hits to display")
    
    # Status subparser
    subparsers.add_parser("status", help="Displays current database stats and connections")
    
    args = parser.parse_args()
    
    if args.command == "chat" or args.command is None:
        asyncio.run(run_chat())
    elif args.command == "lookup":
        asyncio.run(run_lookup(args.query, args.limit))
    elif args.command == "status":
        run_status()
