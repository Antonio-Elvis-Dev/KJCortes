import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from kjcortes import agendador, config
from kjcortes.db import Banco
from kjcortes.redes import ErroRede, Resultado, publicadores
from kjcortes.redes.instagram import Instagram
from kjcortes.redes.tiktok import TikTok, plano_de_pedacos
from kjcortes.web.app import criar_app


class FalsoTikTok:
    """Simula a API do TikTok e guarda o que recebeu."""

    def __init__(self, privacidades=("SELF_ONLY",), status="PUBLISH_COMPLETE"):
        self.pedidos = []
        self.privacidades = list(privacidades)
        self.status = status

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.pedidos.append(req)
        u = str(req.url)
        ok = {"error": {"code": "ok", "message": ""}}
        if u.endswith("/v2/oauth/token/"):
            return httpx.Response(200, json={"access_token": "AT", "refresh_token": "RT", "expires_in": 86400,
                                             "refresh_expires_in": 31536000, "open_id": "o1"})
        if u.endswith("/creator_info/query/"):
            return httpx.Response(200, json={**ok, "data": {"creator_username": "canalcortes", "privacy_level_options": self.privacidades,
                                                            "max_video_post_duration_sec": 600}})
        if u.endswith("/video/init/"):
            return httpx.Response(200, json={**ok, "data": {"publish_id": "p123", "upload_url": "https://upload.tiktok/x"}})
        if u.startswith("https://upload.tiktok/"):
            return httpx.Response(201)
        if u.endswith("/status/fetch/"):
            return httpx.Response(200, json={**ok, "data": {"status": self.status, "publicaly_available_post_id": [777],
                                                            "fail_reason": "spam"}})
        return httpx.Response(404)


class FalsoInstagram:
    def __init__(self):
        self.pedidos = []
        self.estado = "IN_PROGRESS"

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.pedidos.append(req)
        u = str(req.url)
        if "/me?" in u:
            return httpx.Response(200, json={"user_id": "17840", "username": "canalcortes"})
        if u.endswith("/17840/media"):
            return httpx.Response(200, json={"id": "c1", "uri": "https://rupload"})
        if "rupload.facebook.com" in u:
            return httpx.Response(200, json={"success": True})
        if "/c1?" in u:
            return httpx.Response(200, json={"status_code": self.estado})
        if u.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "m9"})
        if "/m9?" in u:
            return httpx.Response(200, json={"permalink": "https://instagram.com/reel/abc"})
        return httpx.Response(404, json={"error": {"message": "nao achou"}})


@pytest.fixture
def base(tmp_path):
    banco = Banco(tmp_path / "t.db")
    sid = banco.criar_streamer(nome="Fulano", canal_twitch="https://twitch.tv/fulano")
    banco.criar_autorizacao(sid, "contrato", "2026-01-01")
    vid = banco.criar_video(sid, "https://twitch.tv/videos/1")
    mp4 = tmp_path / "c.mp4"
    mp4.write_bytes(b"0" * 1000)
    cid = banco.criar_corte(video_id=vid, streamer_id=sid, numero=1, arquivo=str(mp4), inicio=0, fim=30,
                            titulo="T", legenda_tiktok="leg tt", legenda_instagram="leg ig",
                            titulo_youtube="T #shorts", descricao_youtube="desc")
    banco.revisar_corte(cid, "aprovado")
    cfg = config.carregar(None)
    cfg["pastas"]["dados"] = str(tmp_path / "d")
    cfg["redes"]["tiktok"] = {"client_key": "ck", "client_secret": "cs"}
    return banco, cfg, cid, sid


def test_plano_de_pedacos():
    assert plano_de_pedacos(1000) == (1000, 1)
    tam, n = plano_de_pedacos(25 * 1024 * 1024)
    assert n == 2 and tam == 10 * 1024 * 1024  # o último pedaço leva os 5 MB de sobra


def test_tiktok_conecta_publica_e_verifica(base):
    banco, cfg, cid, _ = base
    api = FalsoTikTok()
    tt = TikTok(banco, cfg, httpx.Client(transport=httpx.MockTransport(api)))
    url, sessao = tt.iniciar_autorizacao("http://localhost:8000/contas/tiktok/callback")
    assert "client_key=ck" in url and "code_challenge=" in url
    tt.concluir_autorizacao("CODE", "http://localhost:8000/contas/tiktok/callback", sessao)
    assert banco.conta("tiktok")["nome"] == "@canalcortes"
    troca = api.pedidos[0].content.decode()
    assert "code_verifier=" in troca and "client_secret=cs" in troca

    with pytest.raises(ErroRede, match="não permitida"):
        tt.publicar(banco.corte(cid), {"privacidade": "PUBLIC_TO_EVERYONE"})

    res = tt.publicar(banco.corte(cid), {"privacidade": "SELF_ONLY"})
    assert res == Resultado("processando", "p123")
    init = json.loads(next(p for p in api.pedidos if str(p.url).endswith("/video/init/")).content)
    assert init["post_info"]["title"] == "leg tt" and init["source_info"]["video_size"] == 1000
    put = next(p for p in api.pedidos if p.method == "PUT")
    assert put.headers["Content-Range"] == "bytes 0-999/1000"

    feito = tt.verificar({"id_externo": "p123", "url": ""})
    assert feito.status == "publicada" and feito.url == "https://www.tiktok.com/@canalcortes/video/777"
    api.status = "FAILED"
    with pytest.raises(ErroRede, match="spam"):
        tt.verificar({"id_externo": "p123", "url": ""})


def test_tiktok_renova_token_expirado(base):
    banco, cfg, _, _ = base
    api = FalsoTikTok()
    tt = TikTok(banco, cfg, httpx.Client(transport=httpx.MockTransport(api)))
    banco.salvar_conta("tiktok", {"access_token": "velho", "refresh_token": "RT", "expira_em": time.time() - 10}, "@x")
    tt.info_criador()
    assert "grant_type=refresh_token" in api.pedidos[0].content.decode()
    assert banco.conta("tiktok")["credenciais"]["access_token"] == "AT"


def test_instagram_fluxo(base):
    banco, cfg, cid, _ = base
    api = FalsoInstagram()
    ig = Instagram(banco, cfg, httpx.Client(transport=httpx.MockTransport(api)))
    assert ig.conectar_com_token(" TOKEN ") == "canalcortes"
    res = ig.publicar(banco.corte(cid), {})
    assert res.status == "processando" and res.id_externo == "c1"
    envio = next(p for p in api.pedidos if "rupload" in str(p.url))
    assert envio.headers["file_size"] == "1000" and envio.headers["Authorization"] == "OAuth TOKEN"
    assert ig.verificar({"id_externo": "c1", "url": ""}).status == "processando"
    api.estado = "FINISHED"
    feito = ig.verificar({"id_externo": "c1", "url": ""})
    assert feito.status == "publicada" and feito.url == "https://instagram.com/reel/abc"


def test_agendador_publica_e_bloqueia_sem_autorizacao(base):
    banco, cfg, cid, sid = base
    api = FalsoTikTok()
    pubs = publicadores(banco, cfg, httpx.Client(transport=httpx.MockTransport(api)))
    banco.salvar_conta("tiktok", {"access_token": "AT", "expira_em": time.time() + 3600}, "@canalcortes")

    pid = banco.criar_postagem(cid, "tiktok", "", {"privacidade": "SELF_ONLY"})
    futura = banco.criar_postagem(cid, "tiktok", "2999-01-01T10:00:00", {"privacidade": "SELF_ONLY"})
    ag = agendador.Agendador(banco, pubs)
    ag.rodar_uma_vez()
    assert banco.postagem(pid)["status"] == "processando"
    assert banco.postagem(futura)["status"] == "agendada"  # ainda não é a hora
    ag.rodar_uma_vez()
    p = banco.postagem(pid)
    assert p["status"] == "publicada" and p["url"].endswith("/777") and p["publicada_em"]

    # Autorização revogada depois do corte: a postagem é bloqueada na hora de enviar.
    for a in banco.autorizacoes(sid):
        banco.revogar_autorizacao(a["id"])
    outra = banco.criar_postagem(cid, "tiktok", "", {"privacidade": "SELF_ONLY"})
    antes = len(api.pedidos)
    ag.rodar_uma_vez()
    assert banco.postagem(outra)["status"] == "erro" and "autorização" in banco.postagem(outra)["erro"]
    assert len(api.pedidos) == antes


def test_agendador_marca_envio_interrompido(base):
    banco, cfg, cid, _ = base
    pid = banco.criar_postagem(cid, "youtube")
    banco.atualizar_postagem(pid, status="enviando")
    ag = agendador.Agendador(banco, publicadores(banco, cfg))
    ag._thread.start = lambda: None
    ag.iniciar()
    assert banco.postagem(pid)["status"] == "erro"


def test_youtube_publica(base, monkeypatch):
    banco, cfg, cid, _ = base
    yt = publicadores(banco, cfg)["youtube"]
    recebido = {}

    class Pedido:
        def next_chunk(self):
            return None, {"id": "yt1"}

    class Videos:
        def insert(self, part, body, media_body):
            recebido.update(body=body)
            return Pedido()

    class Servico:
        def videos(self):
            return Videos()

    monkeypatch.setattr(yt, "_credenciais", lambda: object())
    monkeypatch.setattr(yt, "_servico", lambda cred: Servico())
    res = yt.publicar(banco.corte(cid), {"privacidade": "unlisted"})
    assert res.url == "https://www.youtube.com/shorts/yt1"
    assert recebido["body"]["status"]["privacyStatus"] == "unlisted"
    assert recebido["body"]["snippet"]["title"] == "T #shorts"


def test_painel_postar(base):
    banco, cfg, cid, _ = base
    api = FalsoTikTok()
    app = criar_app(cfg, iniciar_fila=False, http=httpx.Client(transport=httpx.MockTransport(api)))
    # usa o mesmo banco do teste
    c = TestClient(app)
    b = app.state.banco
    sid = b.criar_streamer(nome="Z", canal_twitch="https://twitch.tv/z")
    b.criar_autorizacao(sid, "contrato", "2026-01-01")
    vid = b.criar_video(sid, "u")
    corte = b.criar_corte(video_id=vid, streamer_id=sid, numero=1, arquivo=str(banco.corte(cid)["arquivo"]),
                          inicio=0, fim=30, titulo="T", legenda_tiktok="x")

    r = c.post(f"/cortes/{corte}/postar", data={"rede_tiktok": "on"}, follow_redirects=False)
    assert "Aprove" in httpx.URL(r.headers["location"]).params["erro"]
    b.revisar_corte(corte, "aprovado")
    r = c.post(f"/cortes/{corte}/postar", data={"rede_tiktok": "on"}, follow_redirects=False)
    assert "Conecte" in httpx.URL(r.headers["location"]).params["erro"] or "música" in httpx.URL(r.headers["location"]).params["erro"]

    b.salvar_conta("tiktok", {"access_token": "AT", "expira_em": time.time() + 3600}, "@canalcortes")
    pagina = c.get(f"/cortes/{corte}")
    assert "Confirmação de Uso de Música" in pagina.text and "Só eu" in pagina.text
    r = c.post(f"/cortes/{corte}/postar", data={"rede_tiktok": "on", "tiktok_privacidade": "SELF_ONLY"}, follow_redirects=False)
    assert "música" in httpx.URL(r.headers["location"]).params["erro"]
    dados = {"rede_tiktok": "on", "tiktok_privacidade": "SELF_ONLY", "tiktok_consentimento": "on",
             "agendar_para": "2999-01-01T10:00"}
    c.post(f"/cortes/{corte}/postar", data=dados)
    c.post(f"/cortes/{corte}/postar", data=dados)  # repetido: não duplica
    ps = b.postagens(corte)
    assert len(ps) == 1 and ps[0]["agendada_para"] == "2999-01-01T10:00:00"
    assert c.get("/postagens").status_code == 200
    c.post(f"/postagens/{ps[0]['id']}/cancelar")
    assert b.postagem(ps[0]["id"])["status"] == "cancelada"
    c.post(f"/postagens/{ps[0]['id']}/repetir")
    assert len(b.postagens(corte)) == 2

    assert c.get("/contas").status_code == 200
    r = c.get("/contas/tiktok/conectar", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith("https://www.tiktok.com/v2/auth/authorize/")
    estado = httpx.URL(r.headers["location"]).params["state"]
    r = c.get(f"/contas/tiktok/callback?code=C&state={estado}", follow_redirects=False)
    assert "ok=" in r.headers["location"]
    r = c.get("/contas/tiktok/callback?code=C&state=falso", follow_redirects=False)
    assert "erro=" in r.headers["location"]
