from sentence_transformers import SentenceTransformer

# 대칭(symmetric) 임베딩 모델: 쿼리/문서를 동일 방식으로 임베딩
# 한국어에 최적화된 멀티태스킹 SBERT 모델
model = SentenceTransformer("jhgan/ko-sbert-multitask")

def get_embedding(text: str):
    """주어진 텍스트의 임베딩을 반환합니다.

    - 대칭 임베딩 모델을 사용하므로 입력 종류와 무관하게 동일 방식으로 인코딩합니다.
    - 코사인 유사도 일관성을 위해 단위 벡터 정규화를 수행합니다.
    """
    return model.encode(text, normalize_embeddings=True).tolist()
