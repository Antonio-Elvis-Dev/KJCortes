"""Textos de postagem de cada rede, sempre com crédito e menção ao streamer."""

from __future__ import annotations

LIMITE_TIKTOK = 2200
LIMITE_INSTAGRAM = 2200
LIMITE_TITULO_YOUTUBE = 100
LIMITE_DESCRICAO_YOUTUBE = 5000


def _hashtags(streamer: dict, extras: tuple[str, ...]) -> str:
    tags: list[str] = []
    for t in (streamer.get("hashtags") or "").replace(",", " ").split() + list(extras):
        t = "#" + t.lstrip("#")
        if len(t) > 1 and t.lower() not in (x.lower() for x in tags):
            tags.append(t)
    return " ".join(tags)


def _credito(streamer: dict, rede: str) -> str:
    arroba = streamer.get(f"arroba_{rede}") or ""
    nome = streamer["nome"]
    quem = f"@{arroba}" if arroba else nome
    linha = f"🎥 Corte da live de {quem}"
    if streamer.get("credito_extra"):
        linha += f"\n{streamer['credito_extra']}"
    return linha + "\nPublicado com autorização do criador."


def _cortar(texto: str, limite: int) -> str:
    return texto if len(texto) <= limite else texto[: limite - 1].rstrip() + "…"


def gerar_textos(streamer: dict, titulo: str, link_original: str) -> dict[str, str]:
    """Gera legenda do TikTok, legenda do Instagram e título/descrição do YouTube Shorts."""
    titulo = (titulo or "").strip() or f"Melhores momentos de {streamer['nome']}"
    canais = [u for u in (streamer.get("canal_twitch"), streamer.get("canal_youtube")) if u]

    tiktok = "\n\n".join(p for p in (
        titulo, _credito(streamer, "tiktok"), _hashtags(streamer, ("cortes", "live")),
    ) if p)

    instagram = "\n\n".join(p for p in (
        titulo, _credito(streamer, "instagram"),
        "Live completa: link na bio do criador." if canais else "",
        _hashtags(streamer, ("cortes", "reels", "live")),
    ) if p)

    titulo_yt = _cortar(f"{titulo} #shorts", LIMITE_TITULO_YOUTUBE)
    descricao_yt = "\n\n".join(p for p in (
        titulo, _credito(streamer, "youtube"),
        f"Vídeo original: {link_original}" if link_original else "",
        "Canais do criador:\n" + "\n".join(canais) if canais else "",
        _hashtags(streamer, ("shorts", "cortes")),
    ) if p)

    return {
        "legenda_tiktok": _cortar(tiktok, LIMITE_TIKTOK),
        "legenda_instagram": _cortar(instagram, LIMITE_INSTAGRAM),
        "titulo_youtube": titulo_yt,
        "descricao_youtube": _cortar(descricao_yt, LIMITE_DESCRICAO_YOUTUBE),
    }
