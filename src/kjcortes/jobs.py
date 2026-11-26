"""Fila de processamento: confere a autorização, gera os cortes e registra no banco."""

from __future__ import annotations

import json
import logging
import queue
import threading
from pathlib import Path

from . import download, pipeline, postagem
from .db import Banco, normalizar_canal

log = logging.getLogger(__name__)


class NaoAutorizado(Exception):
    pass


def conferir_permissao(banco: Banco, streamer_id: int, url: str, info: dict | None) -> None:
    """Só deixa processar vídeo de streamer ativo, com autorização vigente e do canal cadastrado."""
    s = banco.streamer(streamer_id)
    if not s:
        raise NaoAutorizado("Streamer não encontrado")
    if not banco.autorizacao_valida(streamer_id):
        raise NaoAutorizado(f"{s['nome']} não tem autorização vigente cadastrada (ou está inativo)")
    if info is None:  # arquivo local: o streamer foi escolhido explicitamente
        return
    cadastrados = {normalizar_canal(c) for c in (s["canal_twitch"], s["canal_youtube"]) if c}
    if not cadastrados:
        raise NaoAutorizado(f"Cadastre o canal da Twitch ou do YouTube de {s['nome']} antes de processar")
    do_video = {normalizar_canal(u) for u in info.get("_canal_urls", [])}
    if not cadastrados & do_video:
        dono = info.get("uploader") or info.get("channel") or "desconhecido"
        raise NaoAutorizado(
            f"Este vídeo é do canal {dono} ({', '.join(sorted(do_video)) or 'sem link'}), "
            f"que não é um canal cadastrado de {s['nome']}"
        )


def processar(banco: Banco, cfg: dict, video_id: int) -> int:
    """Processa um vídeo da fila. Retorna quantos cortes foram criados."""
    v = banco.video(video_id)
    if not v:
        raise ValueError(f"Vídeo {video_id} não existe")
    banco.atualizar_video(video_id, status="processando", erro="")
    try:
        local = Path(v["url"]).exists()
        info = None if local else download.identificar(v["url"])
        conferir_permissao(banco, v["streamer_id"], v["url"], info)
        streamer = banco.streamer(v["streamer_id"])
        if info:
            banco.atualizar_video(video_id, titulo=info.get("title") or "")

        cortes = pipeline.executar(v["url"], cfg, canal=streamer["nome"], info=info)

        for c in cortes:
            meta = json.loads(c.metadados.read_text(encoding="utf-8"))
            textos = postagem.gerar_textos(streamer, meta.get("titulo", ""), meta.get("link_original", ""))
            banco.criar_corte(
                video_id=video_id, streamer_id=streamer["id"], numero=c.numero,
                arquivo=str(c.video.resolve()), inicio=meta["inicio"], fim=meta["fim"], nota=meta["nota"],
                titulo=meta.get("titulo", ""), link_original=meta.get("link_original", ""),
                transcricao=meta.get("transcricao", ""), metadados=meta, **textos,
            )
        titulo = v["titulo"] or (cortes and json.loads(cortes[0].metadados.read_text(encoding="utf-8"))["fonte"]["titulo"]) or ""
        banco.atualizar_video(video_id, status="pronto", titulo=titulo,
                              pasta_saida=str(cortes[0].video.parent.resolve()) if cortes else "")
        return len(cortes)
    except Exception as erro:
        log.exception("Falha ao processar o vídeo %s", video_id)
        banco.atualizar_video(video_id, status="erro", erro=str(erro)[:2000])
        return 0


class Fila:
    """Processa um vídeo por vez numa thread em segundo plano (a GPU não gosta de dois ao mesmo tempo)."""

    def __init__(self, banco: Banco, cfg: dict):
        self.banco = banco
        self.cfg = cfg
        self._fila: queue.Queue[int] = queue.Queue()
        self._thread = threading.Thread(target=self._rodar, daemon=True, name="kjcortes-fila")

    def iniciar(self) -> None:
        # Vídeos que ficaram pela metade (programa fechado no meio) voltam para a fila.
        for v in self.banco.videos(limite=1000):
            if v["status"] in ("na_fila", "processando"):
                self.banco.atualizar_video(v["id"], status="na_fila")
                self._fila.put(v["id"])
        self._thread.start()

    def adicionar(self, video_id: int) -> None:
        self._fila.put(video_id)

    def _rodar(self) -> None:
        while True:
            video_id = self._fila.get()
            try:
                processar(self.banco, self.cfg, video_id)
            finally:
                self._fila.task_done()
