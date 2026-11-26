"""YouTube Shorts: YouTube Data API v3 (videos.insert).

Projetos do Google Cloud não verificados só conseguem enviar vídeos como privados
até passarem pela auditoria da API. A cota padrão permite cerca de 6 envios por dia.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import ErroRede, Publicador, Resultado

ESCOPOS = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]
PRIVACIDADES = {"public": "Público", "unlisted": "Não listado", "private": "Privado"}


class YouTube(Publicador):
    rede = "youtube"
    nome = "YouTube Shorts"

    def _segredo(self) -> Path:
        pasta = Path(self.cfg.get("pastas", {}).get("dados", "dados"))
        return Path(self.opcoes.get("client_secret") or pasta / "youtube_client_secret.json")

    def configurado(self) -> bool:
        return self._segredo().exists()

    def _fluxo(self, redirect_uri: str, estado: str | None = None):
        from google_auth_oauthlib.flow import Flow

        return Flow.from_client_secrets_file(str(self._segredo()), scopes=ESCOPOS, redirect_uri=redirect_uri, state=estado)

    def iniciar_autorizacao(self, redirect_uri: str) -> tuple[str, dict]:
        fluxo = self._fluxo(redirect_uri)
        url, estado = fluxo.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
        return url, {"state": estado, "verificador": fluxo.code_verifier}

    def concluir_autorizacao(self, code: str, redirect_uri: str, sessao: dict) -> None:
        fluxo = self._fluxo(redirect_uri, sessao.get("state"))
        fluxo.code_verifier = sessao.get("verificador")
        try:
            fluxo.fetch_token(code=code)
        except Exception as e:
            raise ErroRede(f"Google recusou a autorização: {e}")
        cred = fluxo.credentials
        nome = ""
        try:
            canais = self._servico(cred).channels().list(part="snippet", mine=True).execute()
            if canais.get("items"):
                nome = canais["items"][0]["snippet"]["title"]
        except Exception:
            pass
        self.banco.salvar_conta(self.rede, json.loads(cred.to_json()), nome)

    def _credenciais(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        conta = self.conta()
        if not conta:
            raise ErroRede("Conta do YouTube não conectada")
        cred = Credentials.from_authorized_user_info(conta["credenciais"], ESCOPOS)
        if not cred.valid:
            if not cred.refresh_token:
                raise ErroRede("O acesso ao YouTube expirou; conecte a conta de novo")
            try:
                cred.refresh(Request())
            except Exception as e:
                raise ErroRede(f"Não foi possível renovar o acesso ao YouTube: {e}")
            self.banco.salvar_conta(self.rede, json.loads(cred.to_json()), conta["nome"])
        return cred

    def _servico(self, cred):
        from googleapiclient.discovery import build

        return build("youtube", "v3", credentials=cred, cache_discovery=False)

    def publicar(self, corte: dict, opcoes: dict) -> Resultado:
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaFileUpload

        arquivo = Path(corte["arquivo"])
        if not arquivo.exists():
            raise ErroRede(f"Arquivo do corte não encontrado: {arquivo}")
        privacidade = opcoes.get("privacidade") or self.opcoes.get("privacidade_padrao", "public")
        if privacidade not in PRIVACIDADES:
            raise ErroRede(f"Privacidade inválida: {privacidade}")
        corpo = {
            "snippet": {
                "title": corte["titulo_youtube"][:100] or corte["titulo"][:100],
                "description": corte["descricao_youtube"][:5000],
                "categoryId": str(self.opcoes.get("categoria", "20")),
            },
            "status": {"privacyStatus": privacidade, "selfDeclaredMadeForKids": False},
        }
        try:
            pedido = self._servico(self._credenciais()).videos().insert(
                part="snippet,status", body=corpo,
                media_body=MediaFileUpload(str(arquivo), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True),
            )
            resposta = None
            while resposta is None:
                _, resposta = pedido.next_chunk()
        except HttpError as e:
            motivo = e.reason if hasattr(e, "reason") else str(e)
            if "quota" in str(e).lower():
                motivo = "Cota diária da API do YouTube esgotada; tente amanhã"
            raise ErroRede(f"YouTube: {motivo}")
        vid = resposta.get("id", "")
        return Resultado("publicada", vid, f"https://www.youtube.com/shorts/{vid}" if vid else "")
