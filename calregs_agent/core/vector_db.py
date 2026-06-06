import os
import logging
import json
from typing import List, Optional, Dict, Any
import chromadb

from calregs_agent.config import settings
from calregs_agent.core.models import CCRSection, SearchHit
from calregs_agent.core.embeddings import FastEmbedService

logger = logging.getLogger(__name__)

class ChromaStoreManager:
    """
    Connects to local ChromaDB vector database, indexes regulatory documents, and
    performs similarity-based query searches with metadata filters.
    """
    def __init__(self, embed_service: FastEmbedService):
        self.embed_service = embed_service
        self._client: Optional[chromadb.PersistentClient] = None
        self.collection_name = settings.chroma_collection
        self.db_path = settings.chroma_db_path

        # Ensure database directory exists
        os.makedirs(os.path.dirname(self.db_path) or "output", exist_ok=True)

    @property
    def client(self) -> chromadb.PersistentClient:
        if self._client is None:
            logger.info(f"Connecting to ChromaDB persistent store at: {self.db_path}")
            self._client = chromadb.PersistentClient(path=self.db_path)
        return self._client

    def check_connection(self) -> bool:
        try:
            self.client.heartbeat()
            return True
        except Exception as e:
            logger.error(f"Failed ChromaDB heartbeat ping: {e}")
            return False

    def get_collection(self):
        # We specify cosine similarity distance metric in collection metadata
        return self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"}
        )

    def count_points(self) -> int:
        try:
            return self.get_collection().count()
        except Exception as err:
            logger.error(f"Failed to count points: {err}")
            return 0

    async def index_sections(self, sections: List[CCRSection], vectors: List[List[float]]):
        """
        Indexes CCR sections into the Chroma collection. Idempotent.
        """
        if not sections or not vectors:
            logger.warning("Empty records received for indexing transaction. Skipping.")
            return

        if len(sections) != len(vectors):
            raise ValueError(f"Batch dimension mismatch: {len(sections)} sections and {len(vectors)} vectors.")

        collection = self.get_collection()

        ids = []
        embeddings = []
        metadatas = []
        documents = []

        for section, vec in zip(sections, vectors):
            ids.append(section.id)
            embeddings.append(vec)
            documents.append(section.content_markdown)

            # Construct flat metadatas (Chroma does not support nested dicts/lists in metadata)
            meta = {
                "title_number": section.title_number or "",
                "title_name": section.title_name or "",
                "division": section.division or "",
                "chapter": section.chapter or "",
                "subchapter": section.subchapter or "",
                "section_number": section.section_number or "",
                "section_heading": section.section_heading or "",
                "citation": section.citation or "",
                "source_url": section.source_url,
                "retrieved_at": section.retrieved_at,
                "breadcrumb_path_json": json.dumps(section.breadcrumb_path)
            }
            metadatas.append(meta)

        logger.info(f"Upserting {len(ids)} documents into Chroma collection: {self.collection_name}")
        try:
            collection.upsert(
                ids=ids,
                embeddings=embeddings,
                metadatas=metadatas,
                documents=documents
            )
            logger.info("ChromaDB index upsert transaction finalized.")
        except Exception as err:
            logger.error(f"ChromaDB write transaction failed: {err}")
            raise

    async def query_vector_store(
        self, 
        query_vector: List[float], 
        limit: int = 5, 
        filters: Optional[Dict[str, Any]] = None
    ) -> List[SearchHit]:
        """
        Executes semantic search across the collection, returning hits 
        filtered by optional metadata properties.
        """
        collection = self.get_collection()
        logger.info(f"Querying Chroma index. Limit: {limit}, Filter conditions: {filters}")

        # Construct Chroma where filter
        where_filter = None
        if filters:
            conditions = []
            for field, val in filters.items():
                if val is not None:
                    conditions.append({field: {"$eq": val}})
            
            if len(conditions) == 1:
                where_filter = conditions[0]
            elif len(conditions) > 1:
                where_filter = {"$and": conditions}

        try:
            results = collection.query(
                query_embeddings=[query_vector],
                n_results=limit,
                where=where_filter
            )

            hits = []
            if not results or not results["ids"]:
                return hits

            # Parse results
            ids_list = results["ids"][0]
            metadatas_list = results["metadatas"][0]
            documents_list = results["documents"][0]
            # Chroma returns distance metrics. For cosine space, similarity score = 1.0 - distance
            distances_list = results["distances"][0] if "distances" in results else [0.0] * len(ids_list)

            for i in range(len(ids_list)):
                meta = metadatas_list[i]
                doc = documents_list[i]
                dist = distances_list[i]
                
                # Reconstitute breadcrumb
                bc_json = meta.get("breadcrumb_path_json", "[]")
                try:
                    breadcrumbs = json.loads(bc_json)
                except Exception:
                    breadcrumbs = []

                section = CCRSection(
                    id=ids_list[i],
                    title_number=meta.get("title_number") or None,
                    title_name=meta.get("title_name") or None,
                    division=meta.get("division") or None,
                    chapter=meta.get("chapter") or None,
                    subchapter=meta.get("subchapter") or None,
                    section_number=meta.get("section_number") or None,
                    section_heading=meta.get("section_heading") or None,
                    citation=meta.get("citation") or None,
                    breadcrumb_path=breadcrumbs,
                    source_url=meta.get("source_url"),
                    content_markdown=doc,
                    retrieved_at=meta.get("retrieved_at"),
                    metadata={"origin": "chromadb_vault"}
                )

                # Similarity score calculation (range 0.0 to 1.0)
                sim_score = 1.0 - max(0.0, min(1.0, dist))

                hits.append(
                    SearchHit(
                        section=section,
                        score=sim_score
                    )
                )

            logger.info(f"ChromaDB lookup completed. Found {len(hits)} matching documents.")
            return hits
        except Exception as err:
            logger.error(f"Semantic ChromaDB lookup failed: {err}")
            raise
