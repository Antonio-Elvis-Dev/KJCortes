"""Fluxo completo: baixar, transcrever, achar os melhores trechos, cortar e legendar."""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import download, highlights, llm, render, signals, subtitles, transcribe

log = logging.getLogger(__name__)


@dataclass
class Corte:
    numero: int
    video: Path
    metadados: Path
    candidato: highlights.Candidato


def fonte_local(caminho: Path, pasta_cache: Path, canal: str) -> download.Fonte:
    """Trata um arquivo de vídeo do disco como fonte (útil para testes e vídeos já baixados)."""
    caminho = caminho.resolve()
    ident = hashlib.sha1(str(caminho).encode()).hexdigest()[:10]
    duracao = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(caminho)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    ).stdout.strip() or 0)
    (pasta_cache / f"local_{ident}").mkdir(parents=True, exist_ok=True)
    return download.Fonte(ident, str(caminho), caminho.stem, canal, "", "local", duracao, caminho)


def texto_credito(fonte: download.Fonte) -> str:
    nome = fonte.canal or "o streamer"
    linha = f"Corte da live de {nome}"
    if fonte.canal_url:
        linha += f" ({fonte.canal_url})"
    return linha + ". Corte publicado com autorização do criador."


def executar(entrada: str, cfg: dict, canal: str = "", usar_chat: bool = True, legendar: bool = True,
             info: dict | None = None) -> list[Corte]:
    pasta_cache = Path(cfg["pastas"]["cache"])
    pasta_cache.mkdir(parents=True, exist_ok=True)

    caminho = Path(entrada)
    if caminho.exists():
        fonte = fonte_local(caminho, pasta_cache, canal)
        pasta = pasta_cache / f"local_{fonte.id}"
        usar_chat = False
    else:
        fonte = download.baixar_video(entrada, pasta_cache, info)
        pasta = fonte.arquivo.parent
        if canal:
            fonte.canal = canal

    # 1. Sinais
    wav = signals.extrair_audio(fonte.arquivo, pasta / "audio.wav")
    volume = signals.volume_por_segundo(wav)
    duracao = len(volume) or int(fonte.duracao)
    tempos_chat = download.baixar_chat(fonte.url, pasta) if usar_chat else []
    chat = signals.chat_por_segundo(tempos_chat, duracao)

    t = cfg["transcricao"]
    segmentos = transcribe.transcrever(wav, pasta, t["modelo"], t["dispositivo"], t["idioma"])
    fala = signals.fala_por_segundo(segmentos, duracao)

    # 2. Trechos
    c = cfg["cortes"]
    janelas = highlights.gerar_janelas(segmentos, c["duracao_min"], c["duracao_max"], float(duracao))
    if not janelas:
        log.warning("Vídeo curto demais para gerar cortes de %ss", c["duracao_min"])
        return []
    highlights.pontuar(janelas, volume, chat, fala, cfg["pontuacao"])

    if cfg["ia"]["ativa"]:
        # A IA só avalia os melhores pré-candidatos, já sem sobreposição, para economizar.
        pre = highlights.selecionar(janelas, int(cfg["ia"]["max_candidatos"]), 0)
        llm.avaliar(pre, fonte.canal, fonte.titulo, cfg["ia"]["modelo"], float(cfg["pontuacao"]["ia"]))
        janelas = pre
    escolhidos = highlights.selecionar(janelas, int(c["quantidade"]), float(c["intervalo_min"]))
    escolhidos.sort(key=lambda x: x.inicio)
    log.info("%d trechos escolhidos", len(escolhidos))

    # 3. Render
    pasta_saida = Path(cfg["pastas"]["saida"]) / f"{fonte.plataforma}_{fonte.id}"
    pasta_saida.mkdir(parents=True, exist_ok=True)
    v = cfg["video"]
    cortes: list[Corte] = []
    for n, cand in enumerate(escolhidos, start=1):
        nome = f"corte_{n:02d}"
        ass = None
        if legendar:
            palavras = subtitles.palavras_do_trecho(segmentos, cand.inicio, cand.fim)
            ass = subtitles.gerar_ass(palavras, pasta_saida / f"{nome}.ass", int(v["largura"]), int(v["altura"]), cfg["legenda"])
        mp4 = render.renderizar(fonte.arquivo, cand.inicio, cand.fim, pasta_saida / f"{nome}.mp4", v, ass)

        meta = {
            "corte": nome,
            "arquivo": mp4.name,
            "inicio": round(cand.inicio, 2),
            "fim": round(cand.fim, 2),
            "duracao": round(cand.duracao, 2),
            "nota": round(cand.nota, 3),
            "componentes": {k: round(x, 3) for k, x in cand.componentes.items()},
            "titulo": cand.titulo or fonte.titulo,
            "motivo": cand.motivo,
            "transcricao": cand.texto,
            "credito": texto_credito(fonte),
            "link_original": _link_com_tempo(fonte, cand.inicio),
            "fonte": fonte.para_dict(),
        }
        arq_meta = pasta_saida / f"{nome}.json"
        arq_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        cortes.append(Corte(n, mp4, arq_meta, cand))

    (pasta_saida / "resumo.json").write_text(json.dumps(
        {"fonte": fonte.para_dict(), "cortes": [json.loads(c.metadados.read_text(encoding="utf-8")) for c in cortes]},
        ensure_ascii=False, indent=2,
    ), encoding="utf-8")
    return cortes


def _link_com_tempo(fonte: download.Fonte, inicio: float) -> str:
    s = int(inicio)
    if fonte.plataforma == "youtube":
        return f"{fonte.url}{'&' if '?' in fonte.url else '?'}t={s}s"
    if fonte.plataforma.startswith("twitch"):
        h, r = divmod(s, 3600)
        m, s = divmod(r, 60)
        return f"{fonte.url}{'&' if '?' in fonte.url else '?'}t={h}h{m}m{s}s"
    return fonte.url
