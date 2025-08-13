import os
from dotenv import load_dotenv
from elasticsearch import Elasticsearch

# .env 파일 로드
load_dotenv()

ES_HOST = os.getenv("ES_HOST")
ES_USER = os.getenv("ES_USER")
ES_PASSWORD = os.getenv("ES_PASSWORD")
TELEGRAM_CHATS_INDEX_NAME = os.getenv("TELEGRAM_CHATS_INDEX_NAME", "telegram-chats")
SEED_INDEX_NAME = os.getenv("SEED_INDEX_NAME", "intent-seeds")

es = Elasticsearch(ES_HOST, basic_auth=(ES_USER, ES_PASSWORD))

mapping = {
    "mappings": {
        "properties": {
            "id": { "type": "keyword" },
            "chat_id": { "type": "long" },
            "message_id": { "type": "long" },
            "nickname": { "type": "text" },
            "username": { "type": "text" },
            "is_bot": { "type": "boolean" },
            "text": { "type": "text" },
            "timestamp": { "type": "date" },
            "embedding": {
                "type": "dense_vector",
                "dims": 768,
                "index": True,
                "similarity": "cosine"
            }
        }
    }
}

# 시드 인덱스 매핑 및 생성 함수
seed_mapping = {
    "mappings": {
        "properties": {
            "label": { "type": "keyword" },
            "phrase": { "type": "text" },
            "phrase_normalized": { "type": "keyword" },
            "created_at": { "type": "date" },
            "embedding": {
                "type": "dense_vector",
                "dims": 768,
                "index": True,
                "similarity": "cosine"
            }
        }
    }
}

def create_index(index_name: str, body: dict):
    if not es.indices.exists(index=index_name):
        es.indices.create(index=index_name, body=body)
        print(f"✅ Created index: {index_name}")
        
        # 시드 인덱스가 새로 생성된 경우 기본 시드 데이터 추가
        if index_name == SEED_INDEX_NAME:
            add_default_seeds()
    else:
        print(f"⚠️ Index already exists: {index_name}")

def normalize_phrase(s: str) -> str:
    """키워드/문구의 경량 표준화를 수행합니다.
    
    - 앞뒤 공백 제거, 연속 공백 축소, 문장 끝의 구두점 제거, 소문자 계열 정규화(casefold)
    참고: 임베딩은 원문 텍스트를 사용하며, 이 정규화는 메타데이터 용도입니다.
    """
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[?!.。！？…]+$", "", s)
    s = s.casefold()
    return s

def add_default_seeds():
    """기본 시드 데이터를 추가합니다."""
    from embedder import get_embedding
    from datetime import datetime, timezone
    import re
    import hashlib
    import json
    import os
    
    # JSON 파일에서 기본 시드 데이터 로드
    json_path = os.path.join(os.path.dirname(__file__), "default_seeds.json")
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            default_seeds = json.load(f)
    except FileNotFoundError:
        print(f"⚠️ default_seeds.json 파일을 찾을 수 없습니다: {json_path}")
        return
    except json.JSONDecodeError as e:
        print(f"⚠️ default_seeds.json 파일 형식이 잘못되었습니다: {e}")
        return
    
    total_added = 0
    for seed_data in default_seeds:
        label = seed_data["label"]
        phrases = seed_data["phrases"]
        
        for phrase in phrases:
            if not isinstance(phrase, str) or not phrase.strip():
                continue
                
            normalized = normalize_phrase(phrase)
            es_id = hashlib.sha1(f"{label}|{normalized}".encode("utf-8")).hexdigest()
            
            # 이미 존재하는지 확인
            if es.exists(index=SEED_INDEX_NAME, id=es_id):
                continue
                
            # 임베딩 생성 및 저장
            vec = get_embedding(phrase)
            doc = {
                "label": label,
                "phrase": phrase,
                "phrase_normalized": normalized,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "embedding": vec,
            }
            
            try:
                es.index(index=SEED_INDEX_NAME, id=es_id, document=doc)
                total_added += 1
            except Exception as e:
                print(f"⚠️ Failed to add seed: {label} - {phrase}: {e}")
    
    if total_added > 0:
        print(f"✅ Added {total_added} default seeds to {SEED_INDEX_NAME}")
    else:
        print(f"ℹ️ No new seeds added (all already exist)")
