"""
Flask 서비스 목적:
- 임베딩과 함께 채팅 메시지를 저장하여 이후 검색/조회에 활용
- 의도(라벨)별 시드 문구를 임베딩과 함께 관리
- 입력 문장이 시드와의 벡터 유사도를 기반으로 차단 대상인지 판별

핵심 노트:
- 대칭(symmetric) 임베딩 모델을 사용하며, 쿼리/문서를 동일 방식으로 임베딩
- Elasticsearch의 dense_vector를 코사인 유사도와 함께 사용
- knn_search에서 Elasticsearch의 _score는 코사인 유사도(값이 클수록 더 유사함)
"""

from flask import Flask, request, jsonify
from elastic_client import (
    TELEGRAM_CHATS_INDEX_NAME,
    SEED_INDEX_NAME,
    es,
    create_index,
    mapping,
    seed_mapping,
    add_default_seeds,
    normalize_phrase,
)
from embedder import get_embedding
from datetime import datetime, timezone
import re
import hashlib

app = Flask(__name__)

# 시작 시 인덱스가 존재하도록 보장 (시드 인덱스 생성 시 자동으로 기본 시드 추가됨)
create_index(TELEGRAM_CHATS_INDEX_NAME, mapping)
create_index(SEED_INDEX_NAME, seed_mapping)

@app.route("/embed", methods=["POST"])
def embed():
    """채팅 메시지를 임베딩으로 생성하여 색인합니다.

    요구 JSON 필드: text, chat_id, message_id, nickname, username, is_bot, timestamp
    저장 위치: TELEGRAM_CHATS_INDEX_NAME, 문서 ID 형식은 "{chat_id}_{message_id}"
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

    # 향후 검색을 위해 메시지를 임베딩으로 저장 (대칭 모델)
    vector = get_embedding(text)
    # 확인 로그: 임베딩 차원 수 출력
    print(f"embedding length: {len(vector)}")

    es_id = f"{chat_id}_{message_id}"

    # timestamp 전처리: Unix timestamp를 ISO 형식으로 변환
    timestamp = data.get("timestamp")
    if timestamp:
        if isinstance(timestamp, (int, float)):
            # Unix timestamp를 ISO 형식으로 변환
            timestamp = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
        elif isinstance(timestamp, str):
            # 이미 문자열이면 그대로 사용 (ISO 형식인지 확인)
            try:
                datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            except ValueError:
                # 잘못된 형식이면 현재 시간으로 대체
                timestamp = datetime.now(timezone.utc).isoformat()
    else:
        # timestamp가 없으면 현재 시간 사용
        timestamp = datetime.now(timezone.utc).isoformat()

    doc = {
        "id": es_id,  # chat_id_message_id 형식으로 저장
        "chat_id": chat_id,
        "message_id": message_id,
        "nickname": data.get("nickname"),
        "username": data.get("username"),
        "is_bot": data.get("is_bot"),
        "text": text,
        "timestamp": timestamp,
        "embedding": vector
    }

    es.index(index=TELEGRAM_CHATS_INDEX_NAME, id=es_id, document=doc)
    return jsonify({"message": "Indexed successfully"}), 201


@app.route("/seeds", methods=["POST"])
def add_seeds():
    """특정 라벨에 대해 하나 이상의 시드 문구를 추가합니다.

    요청 본문:
      - label: 문자열 (필수)
      - phrases: 문자열 또는 문자열 배열 (필수)

    각 문구는 kNN 매칭을 위해 임베딩과 함께 저장됩니다.
    """
    data = request.json or {}
    label = data.get("label")
    phrases = data.get("phrases")

    if not label:
        return jsonify({"error": "label is required"}), 400

    if phrases is None:
        return jsonify({"error": "phrases is required (string or array)"}), 400
    # 'phrases'는 단일 문자열과 문자열 배열을 모두 허용
    if isinstance(phrases, str):
        phrases = [phrases]
    elif not isinstance(phrases, list):
        return jsonify({"error": "phrases must be a string or an array of strings"}), 400



    results = []
    for p in phrases:
        if not isinstance(p, str) or not p.strip():
            continue
        normalized = normalize_phrase(p)
        es_id = hashlib.sha1(f"{label}|{normalized}".encode("utf-8")).hexdigest()
        # 대칭 모델: 시드 문구를 동일 방식으로 임베딩하여 색인
        vec = get_embedding(p)
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


@app.route("/seed-matches", methods=["POST"])
def should_block():
    """입력 텍스트를 차단해야 하는지 여부를 반환합니다.

    로직:
      - 입력과 시드를 동일 방식으로 임베딩
      - 시드 임베딩에 대해 kNN 상위 1개 검색
      - Elasticsearch의 _score를 코사인 유사도로 해석
      - 유사도 >= 임계값이면 차단으로 판단

    요청 JSON:
      - text: 문자열 (필수)
      - threshold: [0,1] 범위의 실수, 기본값 0.8
      - label: 문자열(선택) 또는 labels: 문자열 배열(선택) — 시드 범위를 필터링
    """
    data = request.json or {}
    text = data.get("text")
    if not text or not isinstance(text, str) or not text.strip():
        return jsonify({"error": "text is required"}), 400

    # 임계값 기본값 처리
    try:
        threshold = float(data.get("threshold", 0.9))
    except (TypeError, ValueError):
        threshold = 0.9

    # 선택적 라벨 필터 구성
    filters = None
    if isinstance(data.get("label"), str) and data.get("label").strip():
        filters = [{"term": {"label": data.get("label")}}]
    elif isinstance(data.get("labels"), list) and data.get("labels"):
        labels = [l for l in data.get("labels") if isinstance(l, str) and l.strip()]
        if labels:
            filters = [{"terms": {"label": labels}}]

    # 대칭 모델: 사용자 입력을 동일 방식으로 임베딩
    vector = get_embedding(text)

    def _search_top_hit() -> dict | None:
        try:
            res = es.knn_search(
                index=SEED_INDEX_NAME,
                knn={
                    "field": "embedding",
                    "query_vector": vector,
                    "k": 1,
                    "num_candidates": 100,
                },
                _source=["label", "phrase"],
                filter=filters,
            )
            hits_local = res.get("hits", {}).get("hits", [])
            return hits_local[0] if hits_local else None
        except Exception:
            return None

    def _format_no_hit() -> tuple[dict, int]:
        return ({
            "block": False,
            "label": None,
            "similarity": None,
            "distance": None,
            "threshold": threshold,
            "reason": "no_seed_match",
        }, 200)

    def _format_with_hit(top: dict) -> tuple[dict, int]:
        top_label_local = top.get("_source", {}).get("label")
        raw_score_local = top.get("_score")
        sim_score_local = None if raw_score_local is None else float(raw_score_local)
        dist_local = None if sim_score_local is None else (1.0 - sim_score_local)
        block_local = (sim_score_local is not None) and (sim_score_local >= threshold)
        return ({
            "block": bool(block_local),
            "label": top_label_local,
            "similarity": sim_score_local,
            "distance": dist_local,
            "threshold": threshold,
        }, 200)

    top_hit = _search_top_hit()
    body, status = _format_no_hit() if top_hit is None else _format_with_hit(top_hit)
    return jsonify(body), status


@app.route("/labels", methods=["GET"])
def list_labels():
    """현재 등록된 시드 라벨 목록을 반환합니다."""
    try:
        res = es.search(
            index=SEED_INDEX_NAME,
            size=0,
            aggs={
                "labels": {
                    "terms": {
                        "field": "label",
                        "size": 1000
                    }
                }
            }
        )
        buckets = res.get("aggregations", {}).get("labels", {}).get("buckets", [])
        labels = [b.get("key") for b in buckets]
        return jsonify({
            "count": len(labels),
            "labels": labels
        })
    except Exception as e:
        return jsonify({"error": "failed_to_list_labels", "detail": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=True, port=5001)
