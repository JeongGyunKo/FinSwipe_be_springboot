FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# Runtime-only packages. Keep this list small so the image remains lean.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch first. Zeabur runs this service on CPU, so CUDA/NVIDIA
# wheels only make the image much larger without improving runtime performance.
# Then install the local package without dependency resolution so pip does not
# override torch with a CUDA-linked build from the default index.
COPY pyproject.toml README.md ./
COPY app ./app
RUN python -m pip install --upgrade pip setuptools wheel \
    && python -m pip install "torch==2.6.0+cpu" \
        --index-url https://download.pytorch.org/whl/cpu \
        --extra-index-url https://pypi.org/simple \
    && python -m pip install --no-deps . \
    && python -m pip install \
        "fastapi>=0.115.0,<1.0.0" \
        "lime>=0.2.0.1,<0.3.0" \
        "numpy>=1.26.0,<3.0.0" \
        "uvicorn[standard]>=0.30.0,<1.0.0" \
        "pydantic>=2.8.0,<3.0.0" \
        "psycopg[binary]>=3.2.0,<4.0.0" \
        "requests>=2.32.0,<3.0.0" \
        "transformers>=4.44.0,<5.0.0" \
    && if python -m pip list --format=freeze | grep -E '^(nvidia-|triton==)' >/dev/null; then \
        echo "ERROR: Unexpected GPU packages installed in CPU build image."; \
        python -m pip list --format=freeze | grep -E '^(nvidia-|triton==)'; \
        exit 1; \
    fi

# Create a non-root runtime user.
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8080

# Web service default. Worker service should override this command with:
# python -m app.workers.enrichment_worker --poll-interval 5
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]