"""Transcrição com marcação de tempo por palavra (faster-whisper, usa a GPU se houver)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class Palavra:
    inicio: float
    fim: float
    texto: str


@dataclass
class Segmento:
    inicio: float
    fim: float
    texto: str
    palavras: list[Palavra] = field(default_factory=list)


def _escolher_dispositivo(pedido: str) -> tuple[str, str]:
    if pedido in ("cuda", "cpu"):
        dispositivo = pedido
    else:
        try:
            import ctranslate2

            dispositivo = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            dispositivo = "cpu"
    return dispositivo, ("float16" if dispositivo == "cuda" else "int8")


def transcrever(audio: Path, pasta: Path, modelo: str, dispositivo: str, idioma: str | None) -> list[Segmento]:
    """Transcreve o áudio e guarda o resultado em pasta/transcricao.json."""
    cache = pasta / f"transcricao_{modelo}.json"
    if cache.exists():
        log.info("Transcrição já existe: %s", cache)
        return carregar(cache)

    from faster_whisper import WhisperModel

    disp, tipo = _escolher_dispositivo(dispositivo)
    log.info("Transcrevendo com %s em %s (%s). Pode demorar em vídeos longos.", modelo, disp, tipo)
    whisper = WhisperModel(modelo, device=disp, compute_type=tipo)
    trechos, info = whisper.transcribe(
        str(audio),
        language=idioma or None,
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
    )
    segmentos: list[Segmento] = []
    for t in trechos:
        palavras = [Palavra(float(p.start), float(p.end), p.word.strip()) for p in (t.words or []) if p.word.strip()]
        segmentos.append(Segmento(float(t.start), float(t.end), t.text.strip(), palavras))
    log.info("Transcrição pronta: %d trechos, idioma %s", len(segmentos), info.language)

    cache.write_text(json.dumps([asdict(s) for s in segmentos], ensure_ascii=False))
    return segmentos


def carregar(caminho: Path) -> list[Segmento]:
    dados = json.loads(Path(caminho).read_text())
    return [
        Segmento(s["inicio"], s["fim"], s["texto"], [Palavra(**p) for p in s.get("palavras", [])])
        for s in dados
    ]
