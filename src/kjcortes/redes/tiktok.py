"""TikTok: Content Posting API (Direct Post).

Apps ainda não auditados pelo TikTok só conseguem postar como privado (SELF_ONLY).
Depois da auditoria, as opções de privacidade vêm do creator_info da conta.
"""

from __future__ import annotations

import base64
import hashlib
import math
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

from . import ErroRede, Publicador, Resultado

API = "https://open.tiktokapis.com"
AUTORIZAR = "https://www.tiktok.com/v2/auth/authorize/"
ESCOPOS = "user.info.basic,video.publish"
TAMANHO_PEDACO = 10 * 1024 * 1024   # o TikTok aceita pedaços de 5 a 64 MB
MIN_PEDACO = 5 * 1024 * 1024

PRIVACIDADES = {
    "PUBLIC_TO_EVERYONE": "Todos",
    "MUTUAL_FOLLOW_FRIENDS": "Amigos",
    "FOLLOWER_OF_CREATOR": "Seguidores",
    "SELF_ONLY": "Só eu",
}


def plano_de_pedacos(tamanho: int, pedaco: int = TAMANHO_PEDACO) -> tuple[int, int]:
    """(tamanho do pedaço, quantidade). Abaixo de 5 MB vai inteiro; o último pedaço leva a sobra."""
    if tamanho < MIN_PEDACO:
        return tamanho, 1
    return pedaco, max(1, math.floor(tamanho / pedaco))


class TikTok(Publicador):
    rede = "tiktok"
    nome = "TikTok"

    def _chave(self) -> str:
        return self.opcoes.get("client_key") or os.environ.get("TIKTOK_CLIENT_KEY", "")

    def _segredo(self) -> str:
        return self.opcoes.get("client_secret") or os.environ.get("TIKTOK_CLIENT_SECRET", "")

    def configurado(self) -> bool:
        return bool(self._chave() and self._segredo())

    # Autorização ---------------------------------------------------------------

    def iniciar_autorizacao(self, redirect_uri: str) -> tuple[str, dict]:
        estado = secrets.token_urlsafe(16)
        verificador = secrets.token_urlsafe(48)
        desafio = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
        params = {
            "client_key": self._chave(), "scope": ESCOPOS, "response_type": "code",
            "redirect_uri": redirect_uri, "state": estado,
            "code_challenge": desafio, "code_challenge_method": "S256",
        }
        return f"{AUTORIZAR}?{urlencode(params)}", {"state": estado, "verificador": verificador}

    def concluir_autorizacao(self, code: str, redirect_uri: str, sessao: dict) -> None:
        dados = self._token({
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "code_verifier": sessao.get("verificador", ""),
        })
        self._guardar(dados)

    def _token(self, campos: dict) -> dict:
        r = self.http.post(f"{API}/v2/oauth/token/", data={
            "client_key": self._chave(), "client_secret": self._segredo(), **campos,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"})
        dados = r.json()
        if r.status_code != 200 or "access_token" not in dados:
            raise ErroRede(f"TikTok recusou a autorização: {dados.get('error_description') or dados.get('error') or r.text[:300]}")
        return dados

    def _guardar(self, dados: dict) -> dict:
        agora = time.time()
        cred = {
            "access_token": dados["access_token"],
            "refresh_token": dados.get("refresh_token", ""),
            "expira_em": agora + int(dados.get("expires_in", 86400)) - 120,
            "refresh_expira_em": agora + int(dados.get("refresh_expires_in", 0)),
            "open_id": dados.get("open_id", ""),
        }
        nome = ""
        try:
            info = self._api("/v2/post/publish/creator_info/query/", {}, cred["access_token"])
            nome = "@" + info.get("creator_username", "") if info.get("creator_username") else info.get("creator_nickname", "")
        except ErroRede:
            pass
        self.banco.salvar_conta(self.rede, cred, nome)
        return cred

    def _acesso(self) -> str:
        conta = self.conta()
        if not conta:
            raise ErroRede("Conta do TikTok não conectada")
        cred = conta["credenciais"]
        if time.time() >= cred.get("expira_em", 0):
            if not cred.get("refresh_token"):
                raise ErroRede("O acesso ao TikTok expirou; conecte a conta de novo")
            cred = self._guardar(self._token({"grant_type": "refresh_token", "refresh_token": cred["refresh_token"]}))
        return cred["access_token"]

    def _api(self, caminho: str, corpo: dict, token: str | None = None) -> dict:
        r = self.http.post(f"{API}{caminho}", json=corpo, headers={
            "Authorization": f"Bearer {token or self._acesso()}",
            "Content-Type": "application/json; charset=UTF-8",
        })
        try:
            dados = r.json()
        except ValueError:
            raise ErroRede(f"TikTok respondeu {r.status_code}: {r.text[:300]}")
        erro = dados.get("error") or {}
        if r.status_code != 200 or erro.get("code", "ok") != "ok":
            raise ErroRede(f"TikTok: {erro.get('message') or erro.get('code') or r.text[:300]}")
        return dados.get("data") or {}

    # Postagem ------------------------------------------------------------------

    def info_criador(self) -> dict:
        """Privacidades permitidas, duração máxima e se comentários/duetos/stitch estão bloqueados na conta."""
        return self._api("/v2/post/publish/creator_info/query/", {})

    def publicar(self, corte: dict, opcoes: dict) -> Resultado:
        arquivo = Path(corte["arquivo"])
        if not arquivo.exists():
            raise ErroRede(f"Arquivo do corte não encontrado: {arquivo}")
        info = self.info_criador()
        privacidade = opcoes.get("privacidade") or "SELF_ONLY"
        permitidas = info.get("privacy_level_options") or ["SELF_ONLY"]
        if privacidade not in permitidas:
            raise ErroRede(f"Privacidade {privacidade} não permitida nesta conta (permitidas: {', '.join(permitidas)})")
        duracao = corte["fim"] - corte["inicio"]
        maximo = info.get("max_video_post_duration_sec")
        if maximo and duracao > maximo:
            raise ErroRede(f"O corte tem {duracao:.0f}s e a conta aceita no máximo {maximo}s")

        tamanho = arquivo.stat().st_size
        pedaco, quantidade = plano_de_pedacos(tamanho)
        dados = self._api("/v2/post/publish/video/init/", {
            "post_info": {
                "title": corte["legenda_tiktok"][:2200],
                "privacy_level": privacidade,
                "disable_comment": bool(opcoes.get("sem_comentarios")) or bool(info.get("comment_disabled")),
                "disable_duet": bool(opcoes.get("sem_dueto")) or bool(info.get("duet_disabled")),
                "disable_stitch": bool(opcoes.get("sem_stitch")) or bool(info.get("stitch_disabled")),
                "video_cover_timestamp_ms": 1000,
                "brand_content_toggle": False,
                "brand_organic_toggle": False,
            },
            "source_info": {"source": "FILE_UPLOAD", "video_size": tamanho, "chunk_size": pedaco,
                            "total_chunk_count": quantidade},
        })
        publish_id, upload_url = dados.get("publish_id"), dados.get("upload_url")
        if not publish_id or not upload_url:
            raise ErroRede("TikTok não devolveu o endereço de envio")

        with arquivo.open("rb") as f:
            for i in range(quantidade):
                inicio = i * pedaco
                fim = tamanho if i == quantidade - 1 else inicio + pedaco
                f.seek(inicio)
                bloco = f.read(fim - inicio)
                r = self.http.put(upload_url, content=bloco, headers={
                    "Content-Type": "video/mp4", "Content-Length": str(len(bloco)),
                    "Content-Range": f"bytes {inicio}-{fim - 1}/{tamanho}",
                })
                if r.status_code not in (200, 201, 206):
                    raise ErroRede(f"Falha ao enviar o vídeo ao TikTok (parte {i + 1}/{quantidade}): {r.status_code}")
        return Resultado("processando", publish_id)

    def verificar(self, postagem: dict) -> Resultado:
        dados = self._api("/v2/post/publish/status/fetch/", {"publish_id": postagem["id_externo"]})
        status = dados.get("status", "")
        if status == "PUBLISH_COMPLETE":
            ids = dados.get("publicaly_available_post_id") or []
            conta = self.conta() or {}
            arroba = (conta.get("nome") or "").lstrip("@")
            url = f"https://www.tiktok.com/@{arroba}/video/{ids[0]}" if ids and arroba else ""
            return Resultado("publicada", postagem["id_externo"], url)
        if status == "FAILED":
            raise ErroRede(f"TikTok recusou o vídeo: {dados.get('fail_reason') or 'motivo não informado'}")
        return Resultado("processando", postagem["id_externo"])
