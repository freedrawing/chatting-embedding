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
            "chat_title": { "type": "text" },
            "user_id": { "type": "long" },
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
    else:
        print(f"⚠️ Index already exists: {index_name}")
