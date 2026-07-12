FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY . /app
RUN pip install --no-cache-dir -e .[test] && chmod +x /app/scripts/start.sh
CMD ["/app/scripts/start.sh"]
