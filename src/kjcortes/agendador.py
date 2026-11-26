"""Agendador de postagens: publica no horário marcado e acompanha o processamento nas redes."""

from __future__ import annotations

import logging
import threading

from .db import Banco, agora
from .redes import ErroRede, Publicador

log = logging.getLogger(__name__)
INTERVALO = 20  # segundos entre verificações
MAX_VERIFICACOES = 90  # ~30 min processando na rede antes de desistir


def conferir_antes_de_postar(banco: Banco, corte: dict | None, pub: Publicador) -> None:
    """A autorização é conferida de novo na hora de postar: ela pode ter sido revogada depois do corte."""
    if not corte:
        raise ErroRede("O corte foi apagado")
    if corte["status"] != "aprovado":
        raise ErroRede("O corte não está aprovado")
    if not banco.autorizacao_valida(corte["streamer_id"]):
        raise ErroRede(f"{corte['streamer_nome']} não tem mais autorização vigente; postagem bloqueada")
    if not pub.conta():
        raise ErroRede(f"Conta do {pub.nome} não conectada")


def executar_postagem(banco: Banco, pubs: dict[str, Publicador], postagem: dict) -> None:
    pub = pubs[postagem["rede"]]
    pid = postagem["id"]
    try:
        if postagem["status"] == "agendada":
            corte = banco.corte(postagem["corte_id"])
            conferir_antes_de_postar(banco, corte, pub)
            banco.atualizar_postagem(pid, status="enviando", tentativas=postagem["tentativas"] + 1, erro="")
            res = pub.publicar(corte, postagem["opcoes"])
        else:  # processando
            if postagem["tentativas"] > MAX_VERIFICACOES:
                raise ErroRede("A rede demorou demais para processar o vídeo; confira direto no app")
            banco.atualizar_postagem(pid, tentativas=postagem["tentativas"] + 1)
            res = pub.verificar(postagem)
        dados = {"status": res.status, "id_externo": res.id_externo or postagem["id_externo"], "url": res.url or postagem["url"]}
        if res.status == "publicada":
            dados["publicada_em"] = agora()
            log.info("Publicado no %s: %s", pub.nome, dados["url"] or dados["id_externo"])
        banco.atualizar_postagem(pid, **dados)
    except Exception as e:
        log.warning("Postagem %s no %s falhou: %s", pid, pub.nome, e)
        banco.atualizar_postagem(pid, status="erro", erro=str(e)[:1000])


class Agendador:
    def __init__(self, banco: Banco, pubs: dict[str, Publicador]):
        self.banco = banco
        self.pubs = pubs
        self._acordar = threading.Event()
        self._thread = threading.Thread(target=self._rodar, daemon=True, name="kjcortes-agendador")

    def iniciar(self) -> None:
        # Uma postagem que estava "enviando" quando o programa fechou pode ter sido publicada ou não.
        # Para não postar duas vezes, ela vira erro e você decide se tenta de novo.
        for p in self.banco.postagens(limite=1000):
            if p["status"] == "enviando":
                self.banco.atualizar_postagem(p["id"], status="erro",
                                              erro="Envio interrompido (programa fechado). Confira na rede antes de tentar de novo.")
        self._thread.start()

    def acordar(self) -> None:
        self._acordar.set()

    def rodar_uma_vez(self) -> None:
        for p in self.banco.postagens_vencidas():
            executar_postagem(self.banco, self.pubs, p)

    def _rodar(self) -> None:
        while True:
            try:
                self.rodar_uma_vez()
            except Exception:
                log.exception("Erro no agendador")
            self._acordar.wait(INTERVALO)
            self._acordar.clear()
