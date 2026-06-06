#!/usr/bin/env python
import argparse
import asyncio
import json
import logging
import os
import sys
import re
from typing import List, Set, Tuple, Dict
from datetime import datetime, timezone
from urllib.parse import urlparse

# Resolve module paths
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from calregs_agent.config import settings
from calregs_agent.core.scraper import RegScraper
from calregs_agent.core.embeddings import FastEmbedService
from calregs_agent.core.vector_db import ChromaStoreManager

# Set up logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("load_vault")

class IngestionPipeline:
    """
    Coordinates recursive crawler discovery, document parsing,
    local embedding computations, and Chroma DB ingestion.
    """
    def __init__(self, vault_file: str, max_limit: int = 50):
        self.scraper = RegScraper()
        self.embedder = FastEmbedService()
        self.db = ChromaStoreManager(embed_service=self.embedder)
        
        self.vault_file = vault_file
        self.max_limit = max_limit
        self.url_manifest_file = "output/url_manifest.json"
        self.checkpoint_tracker_file = "output/ingestion_state.json"
        self.checkpoints: Dict[str, dict] = {}
        
        # Ensure target directories exist
        os.makedirs("output", exist_ok=True)
        self.recover_checkpoints()

    def recover_checkpoints(self):
        if os.path.exists(self.checkpoint_tracker_file):
            try:
                with open(self.checkpoint_tracker_file, "r", encoding="utf-8") as f:
                    self.checkpoints = json.load(f)
                logger.info(f"Restored {len(self.checkpoints)} index checkpoints.")
            except Exception as err:
                logger.error(f"Failed loading checkpoint status: {err}")
                self.checkpoints = {}
        else:
            self.checkpoints = {}

    def commit_checkpoint(self):
        try:
            with open(self.checkpoint_tracker_file, "w", encoding="utf-8") as f:
                json.dump(self.checkpoints, f, indent=2)
        except Exception as err:
            logger.error(f"Failed persisting checkpoint: {err}")

    def append_backup_vault(self, sections: list):
        logger.info(f"Backing up {len(sections)} sections into local vault JSONL: {self.vault_file}")
        with open(self.vault_file, "a", encoding="utf-8") as f:
            for s in sections:
                f.write(json.dumps(s.model_dump()) + "\n")

    async def ingest_single_url(self, target_url: str) -> Tuple[list, str]:
        logger.info(f"Starting ingestion process: {target_url}")
        
        # 1. Fetch
        page_data = await self.scraper.fetch_page(target_url)
        html_code = page_data.get("html", "")
        markdown_code = page_data.get("markdown", "")
        
        if not html_code and not markdown_code:
            logger.warning(f"Fetch failed: No data retrieved for URL: {target_url}")
            return [], ""
            
        # 2. Parse
        sections = self.scraper.parse_regulations(page_data, target_url)
        if not sections:
            logger.warning(f"Extraction yielded empty list for URL: {target_url}")
            return [], html_code or markdown_code
            
        # 3. Vectorize
        logger.info(f"Generating FastEmbed embeddings for {len(sections)} sections.")
        texts = [s.content_markdown for s in sections]
        vectors = self.embedder.vectorize_list(texts)
        
        # 4. Ingest into ChromaDB
        logger.info(f"Upserting {len(sections)} sections to Chroma collection '{self.db.collection_name}'")
        await self.db.index_sections(sections, vectors)
        
        # 5. Append to local backup vault
        self.append_backup_vault(sections)
        
        return sections, html_code or markdown_code

    async def execute_pipeline(self, seed_url: str, crawl_depth: int = 1):
        """
        Starts the two-stage crawl discovery and DB loader loop.
        """
        logger.info("Verifying vector store connectivity...")
        if not self.db.check_connection():
            logger.critical("Vector store connection failed. Terminating.")
            return

        # ==========================================
        # STAGE 1: SCAN & LINK DISCOVERY
        # ==========================================
        discovered_list = []
        is_restored = False
        
        if os.path.exists(self.url_manifest_file):
            try:
                with open(self.url_manifest_file, "r", encoding="utf-8") as f:
                    discovered_list = json.load(f)
                logger.info(f"Restored {len(discovered_list)} discovered target URLs from {self.url_manifest_file}")
                is_restored = True
            except Exception as err:
                logger.error(f"Unable to read discovered URLs catalog: {err}")
                discovered_list = []

        if not is_restored or not discovered_list or seed_url not in discovered_list:
            logger.info(f"Stage 1: Beginning URL scanner discovery from seed: {seed_url} (depth={crawl_depth})")
            
            queue: List[Tuple[str, int]] = [(seed_url, 0)]
            visited_urls: Set[str] = set()
            sections_catalog: Set[str] = set(discovered_list)
            
            parsed_seed = urlparse(seed_url)
            allowed_domain = parsed_seed.netloc
            
            while queue and len(visited_urls) < self.max_limit:
                curr_url, depth = queue.pop(0)
                if curr_url in visited_urls:
                    continue
                visited_urls.add(curr_url)
                
                logger.info(f"Scanning target node (depth {depth}): {curr_url}")
                try:
                    # If it's a regulation section node, add to catalog
                    # e.g., contains /Document/ on Westlaw or ends with section num / .html on state sites
                    if "/calregs/Document/" in curr_url or ("/title8/" in curr_url.lower() and re.search(r'/[0-9]+[a-zA-Z0-9\.\-]*\.html', curr_url.lower())):
                        sections_catalog.add(curr_url)
                        
                    raw_data = await self.scraper.fetch_page(curr_url)
                    text_content = raw_data.get("html", "") or raw_data.get("markdown", "")
                    
                    if depth < crawl_depth and text_content:
                        discovered_links = self.scraper.extract_links(text_content, curr_url)
                        for url in discovered_links:
                            parsed_url = urlparse(url)
                            # Keep crawler strictly inside Title 8 if seed is from dir.ca.gov
                            if "dir.ca.gov" in allowed_domain and "/title8/" not in parsed_url.path.lower():
                                continue
                            
                            if url not in visited_urls and url not in [item[0] for item in queue]:
                                queue.append((url, depth + 1))
                                
                except Exception as err:
                    logger.error(f"Error executing discovery on URL {curr_url}: {err}")
            
            # Seed fallback check
            if not sections_catalog and ("/calregs/Document/" in seed_url or "dir.ca.gov/title8/" in seed_url):
                sections_catalog.add(seed_url)

            discovered_list = sorted(list(sections_catalog))
            with open(self.url_manifest_file, "w", encoding="utf-8") as f:
                json.dump(discovered_list, f, indent=2)
            logger.info(f"Stage 1 complete: Merged URL discovery list. Catalogued {len(discovered_list)} targets.")
        else:
            logger.info("Seed URL already exists in discovery manifest. Skipping Stage 1 link scan.")

        # ==========================================
        # STAGE 2: PARSE, VECTORIZE AND INDEX
        # ==========================================
        logger.info("Stage 2: Processing URLs into Vector DB collection...")
        pages_processed = 0
        total_blocks_loaded = 0
        
        for idx, url in enumerate(discovered_list):
            if idx >= self.max_limit:
                logger.warning(f"Exceeded max iteration limit of {self.max_limit} URLs. Stopping.")
                break
                
            url_tracker = self.checkpoints.get(url, {})
            if url_tracker.get("status") == "success":
                logger.info(f"URL already indexed (checkpoint hit): {url}")
                total_blocks_loaded += url_tracker.get("blocks_count", 0)
                continue

            try:
                sections, _ = await self.ingest_single_url(url)
                blocks_count = len(sections)
                total_blocks_loaded += blocks_count
                pages_processed += 1
                
                self.checkpoints[url] = {
                    "status": "success",
                    "error_log": None,
                    "blocks_count": blocks_count,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            except Exception as err:
                logger.error(f"Ingestion aborted for target {url}: {err}", exc_info=True)
                self.checkpoints[url] = {
                    "status": "failed",
                    "error_log": str(err),
                    "blocks_count": 0,
                    "retry_count": url_tracker.get("retry_count", 0) + 1,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                
            self.commit_checkpoint()
            await asyncio.sleep(1.0)

        logger.info("=" * 60)
        logger.info("Ingestion Execution Wrap Up Summary:")
        logger.info(f"  Discovered Target Manifest Size : {len(discovered_list)}")
        logger.info(f"  Pages Loaded This Run           : {pages_processed}")
        logger.info(f"  Total Active Blocks Indexed     : {total_blocks_loaded}")
        logger.info(f"  Checkpoints Database File       : {self.checkpoint_tracker_file}")
        logger.info(f"  Audit File Location             : {self.vault_file}")
        logger.info("=" * 60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CCR Ingestion and Indexing Pipeline CLI")
    parser.add_argument(
        "--url", 
        type=str, 
        required=True, 
        help="Seed URL of the regulation document page or chapter index"
    )
    parser.add_argument(
        "--depth", 
        type=int, 
        default=1, 
        help="Depth range for page discovery indexing (default: 1)"
    )
    parser.add_argument(
        "--limit", 
        type=int, 
        default=50, 
        help="Limit of max pages to crawl (default: 50)"
    )
    parser.add_argument(
        "--output", 
        type=str, 
        default="output/ccr_vault.jsonl", 
        help="File path to save the indexed section logs (default: output/ccr_vault.jsonl)"
    )

    args = parser.parse_args()

    asyncio.run(
        IngestionPipeline(vault_file=args.output, max_limit=args.limit).execute_pipeline(
            seed_url=args.url,
            crawl_depth=args.depth
        )
    )
