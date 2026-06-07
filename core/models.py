from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class Entity(BaseModel):
    id: str
    name: str
    schema_type: Optional[str] = None
    datasets: list[str] = []


class Relationship(BaseModel):
    source_id: str
    target_id: str
    rel_type: str


class Document(BaseModel):
    id: str
    text: str
    # provenance
    source: Optional[str] = None        # "sec_edgar" | "courtlistener" | "icij" | "procurement" | "news"
    title: Optional[str] = None         # filing name, case name, article headline
    author: Optional[str] = None        # company, court, publication domain
    jurisdiction: Optional[str] = None  # country code, US state, court circuit
    date: Optional[str] = None          # ISO-8601 date of original document
    doc_length: int = 0                 # character count of full original document (pre-chunking)
    url: Optional[str] = None           # canonical URL of the source document
    # retrieval
    entity_ids: list[str] = []
    score: Optional[float] = None


class SearchResult(BaseModel):
    query: str
    entities: list[Entity]
    documents: list[Document]


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    model: Optional[str] = None
