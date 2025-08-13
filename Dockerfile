# 베이스 이미지: Python 3.13 슬림 버전
FROM python:3.13-slim

# 작업 디렉토리를 /app으로 설정
WORKDIR /app

# 시스템 패키지 설치 및 타임존 설정
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && ln -sf /usr/share/zoneinfo/Asia/Seoul /etc/localtime \
    && echo "Asia/Seoul" > /etc/timezone \
    && dpkg-reconfigure -f noninteractive tzdata \
    && rm -rf /var/lib/apt/lists/*

# 환경변수로 타임존 설정
ENV TZ=Asia/Seoul
# - tzdata 패키지 설치 (타임존 데이터)
# - 한국 시간대(Asia/Seoul) 설정
# - 불필요한 패키지 캐시 정리

# requirements.txt를 먼저 복사하고 pip 최신화 후 의존성 설치
COPY requirements.txt ./
# pip을 최신 버전으로 업그레이드 (로그로 버전 출력)
RUN python -m pip install --upgrade pip && pip --version
RUN pip install --no-cache-dir -r requirements.txt
# - pip 업그레이드 후 의존성을 설치해 Docker 레이어 캐싱 최적화

# 모든 소스 코드를 컨테이너로 복사
COPY . .

# 포트 5001 노출 (문서화용, 실제 노출은 docker run에서)
EXPOSE 5001

# 컨테이너 시작 시 실행할 명령
CMD ["python", "app.py"]