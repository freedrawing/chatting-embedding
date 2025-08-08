"""
Flask service for:
- Storing chat messages with embeddings (for later retrieval)
- Managing intent seed phrases with embeddings
- Checking if an input should be blocked using vector similarity against seeds

Key notes:
- Uses E5 model with query/passage prefixes. See embedder.get_embedding
- Elasticsearch dense_vector with cosine similarity
- In knn_search, Elasticsearch returns _score as cosine similarity (higher is more similar)
"""

from flask import Flask, request, jsonify
from elastic_client import (
    TELEGRAM_CHATS_INDEX_NAME,
    SEED_INDEX_NAME,
    es,
    create_index,
    mapping,
    seed_mapping,
)
from embedder import get_embedding
from datetime import datetime, timezone
import re
import hashlib

app = Flask(__name__)

# Ensure indices exist on startup
create_index(TELEGRAM_CHATS_INDEX_NAME, mapping)
create_index(SEED_INDEX_NAME, seed_mapping)

@app.route("/embed", methods=["POST"])
def embed():
    """Embed and index a chat message as a passage embedding.

    Expects JSON body with: text, chat_id, message_id, and optional metadata.
    Stores under TELEGRAM_CHATS_INDEX_NAME using id "{chat_id}_{message_id}".
    """
    print("embed")
    data = request.json
    text = data.get("text")
    chat_id = data.get("chat_id")
    message_id = data.get("message_id")
    
    if not text:
        return jsonify({"error": "No text provided"}), 400
    if chat_id is None or message_id is None:
        return jsonify({"error": "chat_id and message_id are required"}), 400

    # Store message embeddings as passages for future retrieval
    # Passage embedding for stored content (per E5 convention)
    vector = get_embedding(text, kind="passage")
    # Sanity log: should be 768 dimensions for multilingual-e5-base
    print(f"embedding length: {len(vector)}")

    es_id = f"{chat_id}_{message_id}"

    doc = {
        "id": es_id,  # chat_id_message_id 형식으로 저장
        "chat_id": chat_id,
        "message_id": message_id,
        "chat_title": data.get("chat_title"),
        "user_id": data.get("user_id"),
        "username": data.get("username"),
        "is_bot": data.get("is_bot"),
        "text": text,
        "timestamp": data.get("timestamp"),
        "embedding": vector
    }

    es.index(index=TELEGRAM_CHATS_INDEX_NAME, id=es_id, document=doc)
    return jsonify({"message": "Indexed successfully"}), 201


@app.route("/seeds", methods=["POST"])
def add_seeds():
    """Add one or more seed phrases for a given label.

    Body:
      - label: string (required)
      - phrases: string | [string] (required)

    Each phrase is stored with a passage embedding for knn matching.
    """
    data = request.json or {}
    label = data.get("label")
    phrases = data.get("phrases")

    if not label:
        return jsonify({"error": "label is required"}), 400

    if phrases is None:
        return jsonify({"error": "phrases is required (string or array)"}), 400
    # Accept both single string and array input for 'phrases'
    if isinstance(phrases, str):
        phrases = [phrases]
    elif isinstance(phrases, list):
        pass
    else:
        return jsonify({"error": "phrases must be a string or an array of strings"}), 400

    def normalize_phrase(s: str) -> str:
        """Lightweight normalization for keyword/phrase canonicalization.

        - Trim, collapse whitespace, strip trailing punctuation, casefold
        Note: E5 embeddings use full text; this normalization is for metadata only.
        """
        s = (s or "").strip()
        s = re.sub(r"\s+", " ", s)
        s = re.sub(r"[?!.。！？…]+$", "", s)
        s = s.casefold()
        return s

    results = []
    for p in phrases:
        if not isinstance(p, str) or not p.strip():
            continue
        normalized = normalize_phrase(p)
        es_id = hashlib.sha1(f"{label}|{normalized}".encode("utf-8")).hexdigest()
        # Index seed phrases as passages per E5 convention
        vec = get_embedding(p, kind="passage")
        doc = {
            "label": label,
            "phrase": p,
            "phrase_normalized": normalized,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "embedding": vec,
        }
        res = es.index(index=SEED_INDEX_NAME, id=es_id, document=doc)
        results.append({
            "_id": res.get("_id"),
            "result": res.get("result"),
            "phrase": p,
            "label": label,
        })

    return jsonify({
        "message": "Seeds indexed",
        "count": len(results),
        "items": results
    }), 201


@app.route("/filter/should_block", methods=["POST"])
def should_block():
    """Return whether an input text should be blocked.

    Logic:
      - Embed input as a query (E5)
      - knn search top-1 against seed embeddings
      - Interpret Elasticsearch _score as cosine similarity
      - Compare similarity >= threshold -> block

    Request JSON:
      - text: string (required)
      - threshold: float in [0,1], default 0.8
      - label: string (optional) OR labels: [string] to filter seed set
    """
    data = request.json or {}
    text = data.get("text")
    if not text or not isinstance(text, str) or not text.strip():
        return jsonify({"error": "text is required"}), 400

    # threshold default
    try:
        threshold = float(data.get("threshold", 0.8))
    except (TypeError, ValueError):
        threshold = 0.8

    # Optional label filter(s)
    filters = None
    if isinstance(data.get("label"), str) and data.get("label").strip():
        filters = [{"term": {"label": data.get("label")}}]
    elif isinstance(data.get("labels"), list) and data.get("labels"):
        labels = [l for l in data.get("labels") if isinstance(l, str) and l.strip()]
        if labels:
            filters = [{"terms": {"label": labels}}]

    # Embed user input as a query per E5 convention
    vector = get_embedding(text, kind="query")

    try:
        res = es.knn_search(
            index=SEED_INDEX_NAME,
            knn={
                "field": "embedding",
                "query_vector": vector,
                "k": 1,
                "num_candidates": 100
            },
            _source=["label", "phrase"], # 필요한 필드만 반환
            filter=filters
        )
        hits = res.get("hits", {}).get("hits", [])
    except Exception:
        hits = []

    if not hits:
        return jsonify({
            "block": False,
            "label": None,
            "similarity": None,
            "distance": None,
            "threshold": threshold,
            "reason": "no_seed_match"
        })

    top = hits[0]
    top_label = top.get("_source", {}).get("label")
    raw_score = top.get("_score")
    # Important: For Elasticsearch knn with dense_vector(similarity=cosine),
    # _score is cosine similarity (higher is more similar).
    sim_score = None if raw_score is None else float(raw_score)
    dist = None if sim_score is None else (1.0 - sim_score)
    block = (sim_score is not None) and (sim_score >= threshold)

    return jsonify({
        "block": bool(block),
        "label": top_label,
        "similarity": sim_score,
        "distance": dist,
        "threshold": threshold
    })

if __name__ == "__main__":
    app.run(debug=True, port=5001)
