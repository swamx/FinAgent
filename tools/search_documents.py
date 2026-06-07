from vector.retriever import RetrievalService


def search_documents(retrieval: RetrievalService, query: str) -> str:
    result = retrieval.search(query)
    return result.model_dump_json()
