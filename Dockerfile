FROM python:3.11-slim

WORKDIR /app

# libmagic1 is required by python-magic (used for upload MIME-type validation
# in src/ingestion/guardrails.py). The Windows-only python-magic-bin wheel
# bundles its own binary and doesn't need this, but Linux does.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
# Torch/BLAS default to spinning up one thread pool per CPU core, each with
# its own memory buffers - wasteful on a constrained single-core instance
# and a real contributor to OOM on 512MB hosts. Force single-threaded.
ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1
ENV TOKENIZERS_PARALLELISM=false

EXPOSE 8000

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
