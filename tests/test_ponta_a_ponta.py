"""Gera um vídeo sintético e roda o fluxo inteiro, trocando só a transcrição por uma falsa."""

import json
import shutil
import subprocess

import pytest

from kjcortes import config, pipeline, transcribe
from kjcortes.transcribe import Palavra, Segmento

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="precisa do ffmpeg")


def test_fluxo_completo(tmp_path, monkeypatch):
    video = tmp_path / "live.mp4"
    # 120 s de vídeo 16:9; o áudio fica alto entre 70 s e 80 s.
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=s=640x360:r=30:d=120",
        "-f", "lavfi", "-i", "sine=f=440:d=120",
        "-filter_complex", "[1:a]volume='if(between(t,70,80),1.0,0.02)':eval=frame[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(video),
    ], check=True)

    def falsa(audio, pasta, modelo, dispositivo, idioma):
        segs = []
        for i in range(0, 120, 6):
            palavras = [Palavra(i + k * 0.5, i + k * 0.5 + 0.45, f"palavra{k}") for k in range(8)]
            segs.append(Segmento(i, i + 4, " ".join(p.texto for p in palavras), palavras))
        return segs

    monkeypatch.setattr(transcribe, "transcrever", falsa)
    cfg = config.carregar(None)
    cfg["pastas"] = {"cache": str(tmp_path / "cache"), "saida": str(tmp_path / "saida")}
    cfg["cortes"].update(quantidade=2, duracao_min=15, duracao_max=25, intervalo_min=5)
    cfg["video"].update(largura=360, altura=640, encoder="libx264")
    cfg["legenda"]["tamanho"] = 30

    cortes = pipeline.executar(str(video), cfg, canal="StreamerTeste")

    assert len(cortes) == 2
    # O trecho barulhento (70-80 s) precisa estar entre os escolhidos.
    assert any(c.candidato.inicio <= 75 <= c.candidato.fim for c in cortes)
    for c in cortes:
        info = json.loads(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height", "-of", "json", str(c.video)],
            capture_output=True, text=True, check=True).stdout)
        v = next(s for s in info["streams"] if s["codec_type"] == "video")
        assert (v["width"], v["height"]) == (360, 640)
        assert any(s["codec_type"] == "audio" for s in info["streams"])
        meta = json.loads(c.metadados.read_text())
        assert "StreamerTeste" in meta["credito"]
