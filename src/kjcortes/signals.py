"""Sinais por segundo usados para achar os melhores momentos: volume, chat e fala."""

from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np

from .transcribe import Segmento


def extrair_audio(video: Path, destino: Path) -> Path:
    """Extrai o áudio em WAV mono 16 kHz (formato usado pela transcrição e pelo volume)."""
    if destino.exists():
        return destino
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
         "-c:a", "pcm_s16le", str(destino)],
        check=True,
    )
    return destino


def volume_por_segundo(wav: Path) -> np.ndarray:
    """Volume (RMS em dB) de cada segundo do áudio, lido em blocos para não estourar a memória."""
    valores = []
    with wave.open(str(wav), "rb") as w:
        taxa = w.getframerate()
        while True:
            bloco = w.readframes(taxa)
            if not bloco:
                break
            amostras = np.frombuffer(bloco, dtype=np.int16).astype(np.float32) / 32768.0
            rms = float(np.sqrt(np.mean(amostras**2))) if amostras.size else 0.0
            valores.append(20 * np.log10(rms + 1e-6))
    return np.array(valores, dtype=np.float32)


def chat_por_segundo(tempos: list[float], duracao: int) -> np.ndarray:
    serie = np.zeros(duracao, dtype=np.float32)
    for t in tempos:
        i = int(t)
        if 0 <= i < duracao:
            serie[i] += 1
    return serie


def fala_por_segundo(segmentos: list[Segmento], duracao: int) -> np.ndarray:
    """Quantas palavras são ditas em cada segundo."""
    serie = np.zeros(duracao, dtype=np.float32)
    for s in segmentos:
        for p in s.palavras:
            i = int(p.inicio)
            if 0 <= i < duracao:
                serie[i] += 1
    return serie


def normalizar(serie: np.ndarray) -> np.ndarray:
    """Z-score robusto (mediana e MAD), para que sinais de escalas diferentes possam ser somados."""
    if serie.size == 0:
        return serie
    mediana = np.median(serie)
    mad = np.median(np.abs(serie - mediana)) * 1.4826
    if mad < 1e-9:
        desvio = serie.std()
        if desvio < 1e-9:
            return np.zeros_like(serie)
        mad = desvio
    return np.clip((serie - mediana) / mad, -3, 6)
