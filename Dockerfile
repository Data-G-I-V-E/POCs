FROM python:3.11.14-slim

WORKDIR /app

# Install system dependencies for psycopg2-binary and fastembed
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app.py config.py export_data_integrator.py ./
COPY agents/ ./agents/
COPY prompts/ ./prompts/
COPY storage-scripts/ ./storage-scripts/
COPY static/ ./static/

# Copy local RAG stores (JSON + FAISS indexes bundled in image)
COPY agreements_rag_store/ ./agreements_rag_store/
COPY dgft_ftp_rag_store/ ./dgft_ftp_rag_store/

EXPOSE 8000

# Run without --reload in production
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
