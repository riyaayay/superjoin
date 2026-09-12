FROM python:3.11-slim

WORKDIR /app

# Install build essentials if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .
RUN pip install --no-cache-dir -e fact-knowledge-layer

# Environment variables
ENV PORT=8000
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["sh", "-c", "uvicorn fkl.main:app --app-dir fact-knowledge-layer/src --host 0.0.0.0 --port ${PORT}"]
