# Multi-Agent Research Assistant — Production Dockerfile
# Target: Google Cloud Run
# Build: docker build -t mas-research-assistant .
# Run:   docker run -p 8501:8501 --env-file .env mas-research-assistant

FROM python:3.12-slim AS base

# Security: run as non-root
RUN groupadd -r masuser && useradd -r -g masuser masuser

# System deps for FAISS, PDF processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY evaluation_data/test_cases/ ./evaluation_data/test_cases/
COPY pyproject.toml .

# Create data directories
RUN mkdir -p data/uploads data/vector_store data/sessions evaluation_data/results && \
    chown -R masuser:masuser /app

# Switch to non-root user
USER masuser

# Health check (Streamlit listens on 8501)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

# Expose Streamlit port
EXPOSE 8501

# Environment variables (non-secret defaults)
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV DATA_DIR=/app/data
ENV UPLOADS_DIR=/app/data/uploads
ENV VECTOR_STORE_DIR=/app/data/vector_store
ENV BLACKBOARD_DB_PATH=/app/data/blackboard.db

# Entry point — Streamlit UI
CMD ["streamlit", "run", "app/ui/app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]

