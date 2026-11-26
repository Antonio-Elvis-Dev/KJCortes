"""Download do vídeo (yt-dlp) e do chat (chat-downloader, opcional)."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class Fonte:
    """Vídeo de origem já baixado, com os dados usados para creditar o streamer."""

    id: str
    url: str
    titulo: str
    canal: str
    canal_url: str
    plataforma: str
    duracao: float
    arquivo: Path

    def para_dict(self) -> dict:
        d = asdict(self)
        d["arquivo"] = str(self.arquivo)
        return d


def identificar(url: str) -> dict:
    """Lê os dados do vídeo sem baixar (título, canal e os links possíveis do canal)."""
    import yt_dlp

    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
        info = ydl.extract_info(url, download=False)
    info["_canal_urls"] = canais_do_info(info)
    return info


def canais_do_info(info: dict) -> list[str]:
    """Todos os links que identificam o canal dono do vídeo (YouTube tem @handle e /channel/UC...)."""
    urls = [info.get(k) for k in ("uploader_url", "channel_url")]
    plataforma = (info.get("extractor_key") or "").lower()
    if plataforma.startswith("twitch"):
        for k in ("uploader_id", "channel_id", "uploader"):
            if info.get(k):
                urls.append(f"https://www.twitch.tv/{str(info[k]).lower()}")
    if plataforma == "youtube" and info.get("channel_id"):
        urls.append(f"https://www.youtube.com/channel/{info['channel_id']}")
    if plataforma == "youtube" and info.get("uploader_id", "").startswith("@"):
        urls.append(f"https://www.youtube.com/{info['uploader_id']}")
    vistos: list[str] = []
    for u in urls:
        if u and u not in vistos:
            vistos.append(u)
    return vistos


def baixar_video(url: str, pasta_cache: Path, info: dict | None = None) -> Fonte:
    """Baixa o vídeo em até 1080p para pasta_cache/<id>/video.mp4 (reaproveita se já existir)."""
    import yt_dlp

    if info is None:
        info = identificar(url)

    pasta = pasta_cache / _seguro(f"{info.get('extractor_key', 'video')}_{info['id']}")
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / "video.mp4"

    if not arquivo.exists():
        log.info("Baixando %s", info.get("title"))
        opcoes = {
            "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
            "merge_output_format": "mp4",
            "outtmpl": str(pasta / "video.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
        }
        with yt_dlp.YoutubeDL(opcoes) as ydl:
            ydl.download([url])
        if not arquivo.exists():
            raise RuntimeError(f"O download não gerou {arquivo}")
    else:
        log.info("Vídeo já baixado: %s", arquivo)

    fonte = Fonte(
        id=str(info["id"]),
        url=info.get("webpage_url") or url,
        titulo=info.get("title") or "",
        canal=info.get("uploader") or info.get("channel") or "",
        canal_url=(canais_do_info(info) or [""])[0],
        plataforma=(info.get("extractor_key") or "").lower(),
        duracao=float(info.get("duration") or 0),
        arquivo=arquivo,
    )
    (pasta / "fonte.json").write_text(json.dumps(fonte.para_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return fonte


def baixar_chat(url: str, pasta: Path) -> list[float]:
    """Retorna o instante (em segundos) de cada mensagem do chat da live.

    Usa o pacote opcional chat-downloader. Se ele não estiver instalado ou o vídeo
    não tiver chat gravado, devolve uma lista vazia e o sinal de chat é ignorado.
    """
    cache = pasta / "chat.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))

    try:
        from chat_downloader import ChatDownloader
    except ImportError:
        log.info("chat-downloader não instalado; ignorando o chat (pip install 'kjcortes[chat]')")
        return []

    tempos: list[float] = []
    try:
        for msg in ChatDownloader().get_chat(url):
            t = msg.get("time_in_seconds")
            if t is not None and t >= 0:
                tempos.append(float(t))
    except Exception as erro:  # o pacote lança vários tipos de erro para "sem chat"
        log.warning("Não foi possível baixar o chat: %s", erro)
        return []

    cache.write_text(json.dumps(tempos), encoding="utf-8")
    log.info("Chat: %d mensagens", len(tempos))
    return tempos


def _seguro(nome: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in nome)
