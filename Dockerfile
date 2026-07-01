FROM python:3.11-slim

WORKDIR /app

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
