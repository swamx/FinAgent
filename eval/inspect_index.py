"""Inspect what's actually in the OpenSearch index to inform test case design."""
import json
from opensearchpy import OpenSearch

client = OpenSearch([{"host": "localhost", "port": 9200}])

# Source distribution
resp = client.search(index="fintech-docs", body={
    "size": 0,
    "aggs": {
        "sources": {"terms": {"field": "source.keyword", "size": 30}},
    }
})
print("=== Sources ===")
for b in resp["aggregations"]["sources"]["buckets"]:
    print(f"  {b['doc_count']:6d}  {b['key']}")

# Sample 3 docs per source
print("\n=== Sample docs per source ===")
sources = [b["key"] for b in resp["aggregations"]["sources"]["buckets"]]
for src in sources[:8]:
    hits = client.search(index="fintech-docs", body={
        "size": 2,
        "query": {"term": {"source.keyword": src}},
        "_source": ["title", "source", "entity_id", "text"],
    })["hits"]["hits"]
    for h in hits:
        s = h["_source"]
        print(f"\n[{s.get('source')}] id={h['_id']}")
        print(f"  title: {s.get('title','')[:100]}")
        print(f"  entity_id: {s.get('entity_id','')}")
        print(f"  text: {str(s.get('text',''))[:150]}")

# Check if key entities are present
print("\n=== Entity search ===")
for name in ["Abramovich", "Deripaska", "OFAC", "Panama Papers", "sanctions"]:
    r = client.search(index="fintech-docs", body={
        "size": 0,
        "query": {"match": {"text": name}},
    })
    print(f"  '{name}': {r['hits']['total']['value']} docs")
