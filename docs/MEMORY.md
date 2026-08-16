# JARVIS 2.0 — Memory

## Store

SQLite (`memory.repository`) + FTS + hashing embeddings.

## Recall

`memory.retrieval.hybrid_retrieve` ranks by:

- semantic similarity
- keyword overlap
- recency (≈72h half-life)
- importance (1–5)

`JarvisOS.recall_for_prompt` uses hybrid retrieve + `temporal_query_hours` for phrases like `dün` / `yesterday`.

Never dump the full store into the LLM prompt — `memory_recall_limit` / `memory_recall_max_chars` cap the block.
