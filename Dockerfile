FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static
COPY fonts ./fonts

RUN mkdir -p data output
ENV PYTHONUNBUFFERED=1

# Render 注入 PORT 环境变量;本地默认为 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
