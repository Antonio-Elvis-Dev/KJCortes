"""Integrações de postagem com as APIs oficiais de cada rede."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from ..db import Banco


class ErroRede(Exception):
    """Falha ao falar com a rede, com mensagem pronta para mostrar no painel."""


@dataclass
class Resultado:
    status: str            # "publicada" ou "processando" (a rede ainda está processando o vídeo)
    id_externo: str = ""
    url: str = ""


class Publicador:
    rede = ""
    nome = ""

    def __init__(self, banco: Banco, cfg: dict, http: httpx.Client | None = None):
        self.banco = banco
        self.cfg = cfg
        self.opcoes = cfg.get("redes", {}).get(self.rede, {})
        self.http = http or httpx.Client(timeout=httpx.Timeout(60.0, connect=20.0))

    def configurado(self) -> bool:
        """O app da rede (chaves de desenvolvedor) está configurado?"""
        return True

    def conta(self) -> dict | None:
        return self.banco.conta(self.rede)

    def publicar(self, corte: dict, opcoes: dict) -> Resultado:
        raise NotImplementedError

    def verificar(self, postagem: dict) -> Resultado:
        """Consulta uma postagem que ficou 'processando'. Padrão: já está publicada."""
        return Resultado("publicada", postagem["id_externo"], postagem["url"])


def publicadores(banco: Banco, cfg: dict, http: httpx.Client | None = None) -> dict[str, Publicador]:
    from .instagram import Instagram
    from .tiktok import TikTok
    from .youtube import YouTube

    return {p.rede: p for p in (YouTube(banco, cfg, http), TikTok(banco, cfg, http), Instagram(banco, cfg, http))}
