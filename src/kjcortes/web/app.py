"""Painel web local: streamers e autorizações, envio de vídeos e revisão dos cortes."""

from __future__ import annotations

import base64
import hmac
import os
import re
import time
from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..db import STATUS_CORTE, Banco
from ..jobs import Fila

AQUI = Path(__file__).parent
EXTENSOES_PROVA = {".png", ".jpg", ".jpeg", ".webp", ".pdf", ".txt"}
TAMANHO_MAX_PROVA = 20 * 1024 * 1024
TIPOS_AUTORIZACAO = {
    "contrato": "Contrato assinado",
    "mensagem": "Mensagem (DM, Discord, WhatsApp)",
    "email": "E-mail",
    "publico": "Autorização pública (ex.: regras do canal)",
    "outro": "Outro",
}


def criar_app(cfg: dict, iniciar_fila: bool = True) -> FastAPI:
    pasta_dados = Path(cfg["pastas"]["dados"])
    pasta_provas = pasta_dados / "provas"
    pasta_provas.mkdir(parents=True, exist_ok=True)
    banco = Banco(pasta_dados / "kjcortes.db")
    fila = Fila(banco, cfg)
    if iniciar_fila:
        fila.iniciar()

    app = FastAPI(title="KJCortes", docs_url=None, redoc_url=None)
    app.state.banco = banco
    app.state.fila = fila
    app.mount("/static", StaticFiles(directory=AQUI / "static"), name="static")
    tpl = Jinja2Templates(directory=AQUI / "templates")
    tpl.env.globals.update(TIPOS_AUTORIZACAO=TIPOS_AUTORIZACAO, STATUS_CORTE=STATUS_CORTE)
    tpl.env.filters["tempo"] = lambda s: f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{int(s % 60):02d}"

    senha = os.environ.get("KJCORTES_SENHA", "")

    @app.middleware("http")
    async def proteger(request: Request, call_next):
        # Opcional: com KJCORTES_SENHA definida, o painel pede usuário/senha (para quando estiver na VPS).
        if senha:
            cab = request.headers.get("authorization", "")
            ok = False
            if cab.startswith("Basic "):
                try:
                    _, _, dada = base64.b64decode(cab[6:]).decode().partition(":")
                    ok = hmac.compare_digest(dada, senha)
                except Exception:
                    ok = False
            if not ok:
                return Response("Senha necessária", 401, {"WWW-Authenticate": 'Basic realm="KJCortes"'})
        return await call_next(request)

    def voltar(url: str) -> RedirectResponse:
        return RedirectResponse(url, status_code=303)

    # Início -----------------------------------------------------------------

    @app.get("/")
    def inicio(request: Request, erro: str = ""):
        videos = banco.videos(limite=30)
        return tpl.TemplateResponse(request, "inicio.html", {
            "videos": videos,
            "streamers": [s for s in banco.streamers() if s["autorizado"]],
            "contagem": banco.contagem_cortes(),
            "processando": any(v["status"] in ("na_fila", "processando") for v in videos),
            "erro": erro,
        })

    @app.post("/videos")
    def novo_video(streamer_id: int = Form(...), url: str = Form(...)):
        url = url.strip()
        if not url:
            return voltar("/?erro=Informe+o+link+do+vídeo")
        if not banco.autorizacao_valida(streamer_id):
            return voltar("/?erro=Este+streamer+não+tem+autorização+vigente")
        vid = banco.criar_video(streamer_id, url)
        fila.adicionar(vid)
        return voltar("/")

    # Streamers ----------------------------------------------------------------

    @app.get("/streamers")
    def lista_streamers(request: Request):
        return tpl.TemplateResponse(request, "streamers.html", {"streamers": banco.streamers()})

    def _campos_streamer(form) -> dict:
        campos = {k: (form.get(k) or "").strip() for k in Banco.CAMPOS_STREAMER if k != "ativo"}
        campos["ativo"] = form.get("ativo") == "on"
        return campos

    @app.post("/streamers")
    async def criar_streamer(request: Request):
        form = await request.form()
        try:
            sid = banco.criar_streamer(**_campos_streamer(form))
        except ValueError as e:
            raise HTTPException(400, str(e))
        return voltar(f"/streamers/{sid}")

    @app.get("/streamers/{sid}")
    def ver_streamer(request: Request, sid: int, erro: str = ""):
        s = banco.streamer(sid) or _404()
        return tpl.TemplateResponse(request, "streamer.html", {
            "s": s, "autorizacoes": banco.autorizacoes(sid), "vigente": banco.autorizacao_valida(sid),
            "hoje": date.today().isoformat(), "erro": erro,
        })

    @app.post("/streamers/{sid}")
    async def salvar_streamer(request: Request, sid: int):
        banco.streamer(sid) or _404()
        form = await request.form()
        campos = _campos_streamer(form)
        if not campos["nome"]:
            return voltar(f"/streamers/{sid}?erro=O+nome+é+obrigatório")
        banco.atualizar_streamer(sid, **campos)
        return voltar(f"/streamers/{sid}")

    @app.post("/streamers/{sid}/autorizacoes")
    async def nova_autorizacao(sid: int, tipo: str = Form(...), concedida_em: str = Form(...),
                               valida_ate: str = Form(""), descricao: str = Form(""),
                               prova: UploadFile | None = File(None)):
        banco.streamer(sid) or _404()
        if tipo not in TIPOS_AUTORIZACAO:
            return voltar(f"/streamers/{sid}?erro=Tipo+inválido")
        arquivo = ""
        if prova is not None and prova.filename:
            ext = Path(prova.filename).suffix.lower()
            if ext not in EXTENSOES_PROVA:
                return voltar(f"/streamers/{sid}?erro=Formato+de+prova+não+aceito+(use+imagem,+PDF+ou+TXT)")
            conteudo = await prova.read(TAMANHO_MAX_PROVA + 1)
            if len(conteudo) > TAMANHO_MAX_PROVA:
                return voltar(f"/streamers/{sid}?erro=Arquivo+maior+que+20+MB")
            nome = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(prova.filename).stem)[:60]
            arquivo = f"{sid}_{int(time.time())}_{nome}{ext}"
            (pasta_provas / arquivo).write_bytes(conteudo)
        if not descricao.strip() and not arquivo:
            return voltar(f"/streamers/{sid}?erro=Anexe+uma+prova+ou+descreva+a+autorização")
        try:
            banco.criar_autorizacao(sid, tipo, concedida_em, descricao.strip(), arquivo, valida_ate.strip())
        except ValueError:
            return voltar(f"/streamers/{sid}?erro=Data+inválida")
        return voltar(f"/streamers/{sid}")

    @app.post("/autorizacoes/{aid}/revogar")
    def revogar(aid: int):
        a = banco.autorizacao(aid) or _404()
        banco.revogar_autorizacao(aid)
        return voltar(f"/streamers/{a['streamer_id']}")

    @app.get("/autorizacoes/{aid}/prova")
    def ver_prova(aid: int):
        a = banco.autorizacao(aid) or _404()
        if not a["arquivo"]:
            _404()
        caminho = (pasta_provas / a["arquivo"]).resolve()
        if pasta_provas.resolve() not in caminho.parents or not caminho.exists():
            _404()
        return FileResponse(caminho)

    # Cortes ------------------------------------------------------------------

    @app.get("/cortes")
    def lista_cortes(request: Request, status: str = "pendente", video: int | None = None):
        if status not in STATUS_CORTE and status != "todos":
            status = "pendente"
        return tpl.TemplateResponse(request, "cortes.html", {
            "cortes": banco.cortes(None if status == "todos" else status, video),
            "status": status, "contagem": banco.contagem_cortes(), "video": video,
        })

    @app.get("/cortes/{cid}")
    def ver_corte(request: Request, cid: int):
        c = banco.corte(cid) or _404()
        proximo = next((x["id"] for x in reversed(banco.cortes("pendente")) if x["id"] != cid), None)
        return tpl.TemplateResponse(request, "corte.html", {"c": c, "proximo": proximo})

    @app.post("/cortes/{cid}")
    async def salvar_corte(request: Request, cid: int):
        banco.corte(cid) or _404()
        form = await request.form()
        banco.editar_corte(cid, **{k: (form.get(k) or "") for k in Banco.CAMPOS_EDITAVEIS if k in form})
        acao = form.get("acao", "salvar")
        if acao in ("aprovado", "rejeitado", "pendente"):
            banco.revisar_corte(cid, acao)
            proximo = form.get("proximo")
            if acao != "pendente" and proximo and proximo.isdigit():
                return voltar(f"/cortes/{proximo}")
        return voltar(f"/cortes/{cid}")

    @app.get("/midia/cortes/{cid}")
    def midia_corte(cid: int):
        c = banco.corte(cid) or _404()
        caminho = Path(c["arquivo"])
        if not caminho.exists():
            _404()
        return FileResponse(caminho, media_type="video/mp4")

    return app


def _404():
    raise HTTPException(404, "Não encontrado")


def rodar(cfg: dict, host: str = "127.0.0.1", porta: int = 8000) -> None:
    import uvicorn

    uvicorn.run(criar_app(cfg), host=host, port=porta, log_level="info")
