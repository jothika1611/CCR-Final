from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class CCRSection(BaseModel):
    """
    Represents a single canonical section or text chunk extracted from 
    the California Code of Regulations (CCR).
    """
    id: str = Field(..., description="Unique ID for this section, e.g. MD5 hash of url and section detail.")
    title_number: Optional[str] = Field(None, description="The regulation title number (e.g. '17' or '8')")
    title_name: Optional[str] = Field(None, description="The descriptive name of the regulation title")
    division: Optional[str] = Field(None, description="Division within the CCR hierarchy")
    chapter: Optional[str] = Field(None, description="Chapter details if present")
    subchapter: Optional[str] = Field(None, description="Subchapter or Article details")
    section_number: Optional[str] = Field(None, description="The specific code section code (e.g. '1234')")
    section_heading: Optional[str] = Field(None, description="Heading/title of this section")
    citation: Optional[str] = Field(None, description="Full canonical citation (e.g. '17 CCR § 1234')")
    breadcrumb_path: List[str] = Field(default_factory=list, description="List representation of the breadcrumb trail")
    source_url: str = Field(..., description="Original URL the content was parsed from")
    content_markdown: str = Field(..., description="Extracted content cleaned as Markdown")
    retrieved_at: str = Field(..., description="ISO 8601 UTC timestamp of retrieval")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional custom metadata fields")


class SearchHit(BaseModel):
    """
    Individual match hit from vector similarity search.
    """
    section: CCRSection = Field(..., description="The matched regulatory document section")
    score: float = Field(..., description="Cosine similarity matching score")
