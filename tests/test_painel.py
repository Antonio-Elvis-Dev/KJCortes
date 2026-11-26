import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kjcortes import config, jobs, postagem
from kjcortes.db import Banco, normalizar_arroba, normalizar_canal
from kjcortes.pipeline import Corte
from kjcortes.highlights import Candidato
from kjcortes.web.app import criar_app


@pytest.fixture
def banco(tmp_path):
    return Banco(tmp_path / "t.db")


def streamer_autorizado(banco, **extra):
    dados = dict(nome="Fulano", canal_twitch="https://www.twitch.tv/fulano", arroba_tiktok="@fulano.tt",
                 arroba_instagram="https://instagram.com/fulano.ig/", hashtags="gaming, #valorant")
    dados.update(extra)
    sid = banco.criar_streamer(**dados)
    banco.criar_autorizacao(sid, "mensagem", "2026-01-01", "DM no Instagram")
    return sid


def test_normalizacoes():
    assert normalizar_arroba("@Fulano") == "Fulano"
    assert normalizar_arroba("https://www.tiktok.com/@fulano?lang=pt") == "fulano"
    assert normalizar_canal("https://www.twitch.tv/Fulano/videos") == normalizar_canal("twitch.tv/fulano")
    assert normalizar_canal("https://m.youtube.com/@x/featured") == "youtube.com/@x"


def test_autorizacao_vigente_revogada_vencida_inativo(banco):
    sid = banco.criar_streamer(nome="A")
    assert banco.autorizacao_valida(sid) is None
    aid = banco.criar_autorizacao(sid, "contrato", "2026-01-01", valida_ate="2026-06-30")
    assert banco.autorizacao_valida(sid, date(2026, 3, 1))
    assert banco.autorizacao_valida(sid, date(2026, 7, 1)) is None  # vencida
    assert banco.autorizacao_valida(sid, date(2025, 12, 1)) is None  # ainda não começou
    banco.atualizar_streamer(sid, ativo=False)
    assert banco.autorizacao_valida(sid, date(2026, 3, 1)) is None
    banco.atualizar_streamer(sid, ativo=True)
    banco.revogar_autorizacao(aid)
    assert banco.autorizacao_valida(sid, date(2026, 3, 1)) is None


def test_conferir_permissao_canal(banco):
    sid = streamer_autorizado(banco)
    jobs.conferir_permissao(banco, sid, "x", {"_canal_urls": ["https://www.twitch.tv/fulano"]})
    with pytest.raises(jobs.NaoAutorizado, match="não é um canal cadastrado"):
        jobs.conferir_permissao(banco, sid, "x", {"uploader": "Outro", "_canal_urls": ["https://www.twitch.tv/outro"]})
    sem = banco.criar_streamer(nome="Sem")
    with pytest.raises(jobs.NaoAutorizado, match="não tem autorização"):
        jobs.conferir_permissao(banco, sem, "x", None)


def test_textos_de_postagem_creditam(banco):
    s = banco.streamer(streamer_autorizado(banco))
    t = postagem.gerar_textos(s, "Clutch insano", "https://www.twitch.tv/videos/1?t=0h1m0s")
    assert "@fulano.tt" in t["legenda_tiktok"] and "#valorant" in t["legenda_tiktok"]
    assert "@fulano.ig" in t["legenda_instagram"]
    assert "Fulano" in t["descricao_youtube"] and "videos/1?t=" in t["descricao_youtube"]
    assert t["titulo_youtube"].endswith("#shorts") and len(t["titulo_youtube"]) <= 100
    longo = postagem.gerar_textos(s, "x" * 300, "")
    assert len(longo["titulo_youtube"]) <= 100


def test_processar_registra_cortes(banco, tmp_path, monkeypatch):
    sid = streamer_autorizado(banco)
    vid = banco.criar_video(sid, "https://www.twitch.tv/videos/1")
    mp4 = tmp_path / "corte_01.mp4"
    mp4.write_bytes(b"x")
    meta = tmp_path / "corte_01.json"
    meta.write_text(json.dumps({"inicio": 10, "fim": 40, "nota": 2.5, "titulo": "Momento", "link_original": "L",
                                "transcricao": "oi", "fonte": {"titulo": "Live"}}), encoding="utf-8")
    monkeypatch.setattr(jobs.download, "identificar", lambda url: {"title": "Live", "_canal_urls": ["https://twitch.tv/fulano"]})
    monkeypatch.setattr(jobs.pipeline, "executar", lambda *a, **k: [Corte(1, mp4, meta, Candidato(10, 40, "oi"))])

    assert jobs.processar(banco, {}, vid) == 1
    assert banco.video(vid)["status"] == "pronto"
    c = banco.cortes("pendente")[0]
    assert c["titulo"] == "Momento" and "@fulano.tt" in c["legenda_tiktok"]


def test_processar_bloqueia_canal_errado(banco, monkeypatch):
    sid = streamer_autorizado(banco)
    vid = banco.criar_video(sid, "https://www.youtube.com/watch?v=x")
    monkeypatch.setattr(jobs.download, "identificar", lambda url: {"uploader": "Outro", "_canal_urls": ["https://www.youtube.com/@outro"]})
    chamado = []
    monkeypatch.setattr(jobs.pipeline, "executar", lambda *a, **k: chamado.append(1))
    assert jobs.processar(banco, {}, vid) == 0
    assert banco.video(vid)["status"] == "erro" and not chamado


@pytest.fixture
def cliente(tmp_path):
    cfg = config.carregar(None)
    cfg["pastas"] = {"cache": str(tmp_path / "c"), "saida": str(tmp_path / "s"), "dados": str(tmp_path / "d")}
    app = criar_app(cfg, iniciar_fila=False)
    return TestClient(app), app.state.banco


def test_painel_fluxo(cliente, tmp_path):
    c, banco = cliente
    assert c.get("/").status_code == 200
    r = c.post("/streamers", data={"nome": "Beltrano", "canal_youtube": "https://youtube.com/@beltrano",
                                   "arroba_tiktok": "@bel", "ativo": "on"}, follow_redirects=False)
    assert r.status_code == 303
    sid = int(r.headers["location"].rsplit("/", 1)[1])

    # Sem autorização, o vídeo não entra na fila.
    r = c.post("/videos", data={"streamer_id": sid, "url": "https://youtube.com/watch?v=1"}, follow_redirects=False)
    assert "erro" in r.headers["location"] and not banco.videos()

    # Prova com extensão proibida é recusada; com PNG é aceita.
    r = c.post(f"/streamers/{sid}/autorizacoes", data={"tipo": "mensagem", "concedida_em": "2026-01-01"},
               files={"prova": ("x.exe", b"MZ", "application/octet-stream")}, follow_redirects=False)
    assert "erro" in r.headers["location"]
    r = c.post(f"/streamers/{sid}/autorizacoes", data={"tipo": "mensagem", "concedida_em": "2026-01-01"},
               files={"prova": ("print dm.png", b"\x89PNG", "image/png")})
    assert r.status_code == 200 and "autorizado" in r.text
    aid = banco.autorizacoes(sid)[0]["id"]
    assert c.get(f"/autorizacoes/{aid}/prova").content == b"\x89PNG"

    r = c.post("/videos", data={"streamer_id": sid, "url": "https://youtube.com/watch?v=1"}, follow_redirects=False)
    assert r.headers["location"] == "/"
    vid = banco.videos()[0]["id"]

    mp4 = tmp_path / "c1.mp4"
    mp4.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    cid = banco.criar_corte(video_id=vid, streamer_id=sid, numero=1, arquivo=str(mp4), inicio=0, fim=30,
                            titulo="Teste <script>", legenda_tiktok="leg")
    pagina = c.get(f"/cortes/{cid}")
    assert pagina.status_code == 200 and "<script>" not in pagina.text  # escapado
    assert c.get(f"/midia/cortes/{cid}").content.startswith(b"\x00\x00\x00\x18")
    assert "Teste" in c.get("/cortes?status=pendente").text

    c.post(f"/cortes/{cid}", data={"titulo": "Novo título", "legenda_tiktok": "editada", "acao": "aprovado"})
    corte = banco.corte(cid)
    assert corte["status"] == "aprovado" and corte["titulo"] == "Novo título" and corte["legenda_tiktok"] == "editada"
    assert banco.contagem_cortes()["aprovado"] == 1

    # Revogar bloqueia novos vídeos.
    c.post(f"/autorizacoes/{aid}/revogar")
    r = c.post("/videos", data={"streamer_id": sid, "url": "https://youtube.com/watch?v=2"}, follow_redirects=False)
    assert "erro" in r.headers["location"]


def test_senha_opcional(tmp_path, monkeypatch):
    monkeypatch.setenv("KJCORTES_SENHA", "segredo")
    cfg = config.carregar(None)
    cfg["pastas"]["dados"] = str(tmp_path / "d")
    c = TestClient(criar_app(cfg, iniciar_fila=False))
    assert c.get("/").status_code == 401
    assert c.get("/", auth=("eu", "segredo")).status_code == 200
