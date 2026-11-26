"""Instagram Reels: API do Instagram com login do Instagram (conta profissional).

A conexão é feita colando um token de acesso gerado no painel de apps da Meta
(Instagram > Configuração da API > Gerar token). O token de longa duração vale
60 dias e é renovado automaticamente.
"""

from __future__ import annotations

import time
from pathlib import Path

from . import ErroRede, Publicador, Resultado

VERSAO = "v23.0"
GRAPH = f"https://graph.instagram.com/{VERSAO}"
UPLOAD = f"https://rupload.facebook.com/ig-api-upload/{VERSAO}"
RENOVAR_APOS = 7 * 24 * 3600


class Instagram(Publicador):
    rede = "instagram"
    nome = "Instagram"

    def _checar(self, r) -> dict:
        try:
            dados = r.json()
        except ValueError:
            raise ErroRede(f"Instagram respondeu {r.status_code}: {r.text[:300]}")
        if r.status_code != 200 or "error" in dados:
            erro = dados.get("error") or {}
            raise ErroRede(f"Instagram: {erro.get('error_user_msg') or erro.get('message') or r.text[:300]}")
        return dados

    def conectar_com_token(self, token: str) -> str:
        token = token.strip()
        if not token:
            raise ErroRede("Cole o token de acesso")
        eu = self._checar(self.http.get(f"{GRAPH}/me", params={"fields": "user_id,username", "access_token": token}))
        if not eu.get("user_id"):
            raise ErroRede("Token sem conta profissional do Instagram associada")
        self.banco.salvar_conta(self.rede, {"access_token": token, "user_id": str(eu["user_id"]), "renovado_em": time.time()},
                                "@" + eu.get("username", ""))
        return eu.get("username", "")

    def _acesso(self) -> tuple[str, str]:
        conta = self.conta()
        if not conta:
            raise ErroRede("Conta do Instagram não conectada")
        cred = conta["credenciais"]
        if time.time() - cred.get("renovado_em", 0) > RENOVAR_APOS:
            try:
                novo = self._checar(self.http.get("https://graph.instagram.com/refresh_access_token", params={
                    "grant_type": "ig_refresh_token", "access_token": cred["access_token"]}))
                cred.update(access_token=novo["access_token"], renovado_em=time.time())
                self.banco.salvar_conta(self.rede, cred, conta["nome"])
            except ErroRede:
                pass  # o token antigo pode continuar valendo; se não valer, a postagem mostra o erro
        return cred["access_token"], cred["user_id"]

    def publicar(self, corte: dict, opcoes: dict) -> Resultado:
        arquivo = Path(corte["arquivo"])
        if not arquivo.exists():
            raise ErroRede(f"Arquivo do corte não encontrado: {arquivo}")
        token, usuario = self._acesso()
        container = self._checar(self.http.post(f"{GRAPH}/{usuario}/media", data={
            "media_type": "REELS", "upload_type": "resumable", "caption": corte["legenda_instagram"][:2200],
            "share_to_feed": "true", "access_token": token,
        }))
        cid = container.get("id")
        if not cid:
            raise ErroRede("Instagram não criou o contêiner do Reels")
        tamanho = arquivo.stat().st_size
        r = self.http.post(f"{UPLOAD}/{cid}", content=arquivo.read_bytes(), headers={
            "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(tamanho),
        })
        self._checar(r)
        return Resultado("processando", cid)

    def verificar(self, postagem: dict) -> Resultado:
        token, usuario = self._acesso()
        cid = postagem["id_externo"]
        if postagem.get("url"):  # já publicado, só faltava o link
            return Resultado("publicada", cid, postagem["url"])
        estado = self._checar(self.http.get(f"{GRAPH}/{cid}", params={"fields": "status_code,status", "access_token": token}))
        codigo = estado.get("status_code")
        if codigo in ("ERROR", "EXPIRED"):
            raise ErroRede(f"Instagram não processou o vídeo: {estado.get('status') or codigo}")
        if codigo != "FINISHED":
            return Resultado("processando", cid)
        publicado = self._checar(self.http.post(f"{GRAPH}/{usuario}/media_publish", data={
            "creation_id": cid, "access_token": token}))
        media = publicado.get("id", "")
        url = ""
        try:
            url = self._checar(self.http.get(f"{GRAPH}/{media}", params={"fields": "permalink", "access_token": token})).get("permalink", "")
        except ErroRede:
            pass
        return Resultado("publicada", media, url)
