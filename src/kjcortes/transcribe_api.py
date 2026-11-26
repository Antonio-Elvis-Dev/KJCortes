"""Transcrição por API compatível com a da OpenAI (Groq, OpenAI etc.), para máquinas sem GPU.

O áudio é dividido em blocos de alguns minutos em MP3 (as APIs limitam o tamanho do
arquivo, em geral 25 MB) e os tempos de cada bloco são somados ao início dele.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

import httpx

from .transcribe import Palavra, Segmento, carregar

log = logging.getLogger(__name__)

BLOCO_SEGUNDOS = 600  # 10 min a 32 kbps ~= 2,4 MB por bloco
URL_PADRAO = "https://api.groq.com/openai/v1"
MODELO_PADRAO = "whisper-large-v3-turbo"


def _duracao(audio: Path) -> float:
    saida = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(audio)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    ).stdout.strip()
    return float(saida or 0)


def _bloco_mp3(audio: Path, inicio: float, duracao: float, destino: Path) -> Path:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{inicio:.3f}", "-t", f"{duracao:.3f}", "-i", str(audio),
         "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "32k", str(destino)],
        check=True,
    )
    return destino


def montar_segmentos(resposta: dict, deslocamento: float) -> list[Segmento]:
    """Converte o verbose_json da API em Segmentos, distribuindo as palavras pelos trechos."""
    palavras = [
        Palavra(float(p["start"]) + deslocamento, float(p["end"]) + deslocamento, str(p["word"]).strip())
        for p in resposta.get("words") or [] if str(p.get("word", "")).strip()
    ]
    trechos = resposta.get("segments") or []
    if not trechos and palavras:
        trechos = [{"start": palavras[0].inicio - deslocamento, "end": palavras[-1].fim - deslocamento,
                    "text": resposta.get("text", "")}]
    segmentos = [Segmento(float(t["start"]) + deslocamento, float(t["end"]) + deslocamento, str(t.get("text", "")).strip())
                 for t in trechos]
    i = 0
    for p in palavras:
        meio = (p.inicio + p.fim) / 2
        while i + 1 < len(segmentos) and meio >= segmentos[i].fim:
            i += 1
        if segmentos:
            segmentos[i].palavras.append(p)
    return [s for s in segmentos if s.texto or s.palavras]


def transcrever_api(audio: Path, pasta: Path, cfg_t: dict, http: httpx.Client | None = None) -> list[Segmento]:
    modelo = cfg_t.get("api_modelo") or MODELO_PADRAO
    cache = pasta / f"transcricao_api_{modelo.replace('/', '_')}.json"
    if cache.exists():
        log.info("Transcrição já existe: %s", cache)
        return carregar(cache)

    chave = os.environ.get("TRANSCRICAO_API_KEY", "")
    if not chave:
        raise RuntimeError("Defina a variável TRANSCRICAO_API_KEY com a chave da API de transcrição")
    url = (cfg_t.get("api_url") or URL_PADRAO).rstrip("/") + "/audio/transcriptions"
    cliente = http or httpx.Client(timeout=httpx.Timeout(300.0, connect=20.0))

    total = _duracao(audio)
    segmentos: list[Segmento] = []
    with tempfile.TemporaryDirectory() as tmp:
        inicio = 0.0
        n = 0
        while inicio < total:
            n += 1
            dur = min(BLOCO_SEGUNDOS, total - inicio)
            mp3 = _bloco_mp3(audio, inicio, dur, Path(tmp) / f"bloco_{n}.mp3")
            log.info("Transcrevendo bloco %d (%.0f-%.0fs) pela API", n, inicio, inicio + dur)
            dados = {"model": modelo, "response_format": "verbose_json",
                     "timestamp_granularities[]": ["word", "segment"]}
            if cfg_t.get("idioma"):
                dados["language"] = cfg_t["idioma"]
            for tentativa in range(4):
                with mp3.open("rb") as f:
                    r = cliente.post(url, headers={"Authorization": f"Bearer {chave}"}, data=dados,
                                     files={"file": (mp3.name, f, "audio/mpeg")})
                if r.status_code == 429 or r.status_code >= 500:
                    espera = float(r.headers.get("retry-after") or 2 ** (tentativa + 2))
                    log.warning("API de transcrição respondeu %s; tentando de novo em %.0fs", r.status_code, espera)
                    time.sleep(min(espera, 120))
                    continue
                break
            if r.status_code != 200:
                raise RuntimeError(f"API de transcrição respondeu {r.status_code}: {r.text[:300]}")
            segmentos.extend(montar_segmentos(r.json(), inicio))
            inicio += dur

    cache.write_text(json.dumps([asdict(s) for s in segmentos], ensure_ascii=False), encoding="utf-8")
    log.info("Transcrição pela API pronta: %d trechos", len(segmentos))
    return segmentos
