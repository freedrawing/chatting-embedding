from sentence_transformers import SentenceTransformer

model = SentenceTransformer("intfloat/multilingual-e5-base")

def get_embedding(text: str, kind: str = "query"):
    """
    Return an embedding for the given text using E5.

    E5 expects different prefixes for queries vs. passages. Use:
    - kind="query" for user inputs
    - kind="passage" for stored phrases/seeds/documents
    """
    prefix = "query" if kind != "passage" else "passage"
    formatted_input = f"{prefix}: {text}"
    # Normalize to unit length to make cosine metrics consistent
    return model.encode(formatted_input, normalize_embeddings=True).tolist()
