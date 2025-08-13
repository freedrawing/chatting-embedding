import os
import torch
from sentence_transformers import SentenceTransformer

# CUDA/MPS 비활성화
os.environ["CUDA_VISIBLE_DEVICES"] = ""
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "0"

torch.use_deterministic_algorithms(True)
torch.set_float32_matmul_precision("high")
torch.set_num_threads(1)

model = SentenceTransformer("jhgan/ko-sbert-multitask", device="cpu").eval()

def get_embedding(text: str):
    """텍스트 임베딩 반환.

    - 대칭 임베딩 모델. 입력 종류와 무관하게 동일 방식으로 인코딩
    - 코사인 유사도 일관성을 위해 단위 벡터로 정규화
    """
    return model.encode(text, normalize_embeddings=True).tolist()
