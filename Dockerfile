# Imagem para CPU (VPS comum). Para GPU NVIDIA, use Dockerfile.gpu.
FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-montserrat curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 kj
WORKDIR /opt/kjcortes
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[chat,ia]"

# Dados persistentes: dados/ (banco e provas), cache/ (vídeos, transcrições, modelos) e saida/ (cortes).
WORKDIR /kjcortes
RUN mkdir -p dados cache saida && chown -R kj:kj /kjcortes
ENV HF_HOME=/kjcortes/cache/modelos \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1
USER kj

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -fsS http://127.0.0.1:8000/saude || exit 1
CMD ["kjcortes", "painel", "--host", "0.0.0.0", "--porta", "8000"]
