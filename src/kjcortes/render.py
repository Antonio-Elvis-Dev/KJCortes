"""Renderização do corte vertical com FFmpeg (NVENC na GPU quando disponível)."""

from __future__ import annotations

import functools
import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def nvenc_disponivel() -> bool:
    """Testa de verdade uma codificação curta com h264_nvenc (não basta o FFmpeg listar o encoder)."""
    try:
        r = subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.1",
             "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True, timeout=30,
        )
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def escolher_encoder(pedido: str) -> str:
    if pedido in ("h264_nvenc", "libx264"):
        return pedido
    return "h264_nvenc" if nvenc_disponivel() else "libx264"


def filtro_video(layout: str, largura: int, altura: int, legenda: str | None) -> str:
    """Monta o filter_complex que gera [v] no formato vertical."""
    if layout == "centro":
        cadeia = f"[0:v]scale=-2:{altura},crop={largura}:{altura}"
    elif layout == "desfoque":
        cadeia = (
            f"[0:v]split=2[a][b];"
            f"[a]scale={largura}:{altura}:force_original_aspect_ratio=increase,crop={largura}:{altura},"
            f"boxblur=25:3,eq=brightness=-0.12[fundo];"
            f"[b]scale={largura}:-2[frente];"
            f"[fundo][frente]overlay=(W-w)/2:(H-h)/2"
        )
    else:
        raise ValueError(f"Layout desconhecido: {layout} (use 'desfoque' ou 'centro')")
    if legenda:
        cadeia += f",ass={legenda}"
    return cadeia + ",setsar=1,format=yuv420p[v]"


def comando_ffmpeg(video: Path, inicio: float, fim: float, saida: Path, layout: str,
                   largura: int, altura: int, encoder: str, legenda: str | None) -> list[str]:
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-ss", f"{inicio:.3f}", "-t", f"{fim - inicio:.3f}", "-i", str(video),
        "-filter_complex", filtro_video(layout, largura, altura, legenda),
        "-map", "[v]", "-map", "0:a?",
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
    ]
    if encoder == "h264_nvenc":
        cmd += ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20"]
    cmd += ["-r", "30", "-movflags", "+faststart", str(saida)]
    return cmd


def renderizar(video: Path, inicio: float, fim: float, saida: Path, cfg_video: dict, legenda: Path | None) -> Path:
    """Gera o .mp4 final. O FFmpeg roda dentro da pasta de saída para a legenda não precisar de escape."""
    encoder = escolher_encoder(cfg_video["encoder"])
    cmd = comando_ffmpeg(
        video.resolve(), inicio, fim, saida.name, cfg_video["layout"],
        int(cfg_video["largura"]), int(cfg_video["altura"]), encoder,
        legenda.name if legenda else None,
    )
    log.info("Renderizando %s (%s)", saida.name, encoder)
    resultado = subprocess.run(cmd, cwd=saida.parent, capture_output=True, text=True)
    if resultado.returncode != 0:
        raise RuntimeError(f"FFmpeg falhou ao gerar {saida.name}:\n{resultado.stderr[-2000:]}")
    return saida
