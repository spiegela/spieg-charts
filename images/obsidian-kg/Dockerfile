FROM python:3.12-slim-bookworm

# TaylorAI/bge-micro-v2 is the model Smart Connections uses, so vectors this
# server computes live in the same space as the plugin's stored ones.
ARG MODEL_REPO=TaylorAI/bge-micro-v2
ARG MODEL_REVISION=3edf6d7de0faa426b09780416fe61009f26ae589

# Few malloc arenas: ONNX Runtime's worker threads otherwise each pin freed heap.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MALLOC_ARENA_MAX=2 \
    KG_VAULT=/vault \
    KG_MODEL_DIR=/opt/model \
    KG_CACHE_DIR=/cache \
    KG_PORT=8080

COPY requirements.txt /tmp/requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && mkdir -p /opt/model/onnx \
    && base="https://huggingface.co/${MODEL_REPO}/resolve/${MODEL_REVISION}" \
    && curl -fsSL -o /opt/model/onnx/model.onnx "${base}/onnx/model.onnx" \
    && curl -fsSL -o /opt/model/tokenizer.json "${base}/tokenizer.json" \
    && echo "9f705befe60d00ca3d8d14c9dd61a3ecfca9f1920a39fbc4a5b056c0ccd977d4  /opt/model/onnx/model.onnx" | sha256sum -c - \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 kg && useradd -u 10001 -g kg -M -d /cache kg \
    && mkdir -p /cache && chown kg:kg /cache

COPY obsidian_kg /app/obsidian_kg
WORKDIR /app

USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["python", "-m", "obsidian_kg.server"]
