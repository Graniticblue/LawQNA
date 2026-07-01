FROM python:3.11-slim

WORKDIR /app

# 컨테이너(비-TTY)에서 startup.py 로그가 버퍼링돼 뭉쳐 나오는 것 방지 — 실시간 스트리밍
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir torch --extra-index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# exec 형식(JSON) + chainlit 앞 exec: SIGTERM이 셸이 아닌 앱에 직접 전달돼 graceful shutdown 보장
CMD ["sh", "-c", "python startup.py && exec chainlit run chainlit_app.py --port=${PORT:-8000} --host=0.0.0.0"]
