import subprocess

import httpx
import pytest
from fastapi.testclient import TestClient

from kjcortes import config, transcribe_api
from kjcortes.web.app import criar_app


def test_montar_segmentos_distribui_palavras():
    resp = {
        "segments": [{"start": 0, "end": 2, "text": "ola pessoal"}, {"start": 2, "end": 4, "text": "tudo bem"}],
        "words": [{"word": "ola", "start": 0.1, "end": 0.5}, {"word": "pessoal", "start": 0.6, "end": 1.2},
                  {"word": "tudo", "start": 2.1, "end": 2.5}, {"word": "bem", "start": 2.6, "end": 3.0}],
    }
    segs = transcribe_api.montar_segmentos(resp, 100)
    assert [s.inicio for s in segs] == [100, 102]
    assert [p.texto for p in segs[1].palavras] == ["tudo", "bem"] and segs[1].palavras[0].inicio == 102.1


def test_transcrever_api_em_blocos(tmp_path, monkeypatch):
    wav = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=d=2.5", "-ac", "1", "-ar", "16000", str(wav)], check=True)
    monkeypatch.setattr(transcribe_api, "BLOCO_SEGUNDOS", 1)
    monkeypatch.setenv("TRANSCRICAO_API_KEY", "chave")
    pedidos = []

    def api(req: httpx.Request):
        pedidos.append(req)
        return httpx.Response(200, json={"segments": [{"start": 0.0, "end": 0.9, "text": "oi"}],
                                         "words": [{"word": "oi", "start": 0.1, "end": 0.4}]})

    segs = transcribe_api.transcrever_api(wav, tmp_path, {"idioma": "pt"}, httpx.Client(transport=httpx.MockTransport(api)))
    assert len(pedidos) == 3  # 2,5 s em blocos de 1 s
    assert [round(s.inicio, 1) for s in segs] == [0.0, 1.0, 2.0]
    corpo = pedidos[0].content
    assert b"whisper-large-v3-turbo" in corpo and b'name="language"' in corpo
    assert pedidos[0].headers["authorization"] == "Bearer chave"
    # segunda vez usa o cache, sem chamar a API
    transcribe_api.transcrever_api(wav, tmp_path, {}, httpx.Client(transport=httpx.MockTransport(api)))
    assert len(pedidos) == 3


def test_transcrever_api_sem_chave(tmp_path, monkeypatch):
    monkeypatch.delenv("TRANSCRICAO_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="TRANSCRICAO_API_KEY"):
        transcribe_api.transcrever_api(tmp_path / "x.wav", tmp_path, {})


def test_config_por_variaveis(tmp_path, monkeypatch):
    arq = tmp_path / "c.yaml"
    arq.write_text("cortes:\n  quantidade: 7\n")
    monkeypatch.setenv("KJCORTES_CONFIG", str(arq))
    monkeypatch.setenv("KJCORTES_URL_PAINEL", "https://cortes.exemplo.com")
    cfg = config.carregar(None)
    assert cfg["cortes"]["quantidade"] == 7 and cfg["redes"]["url_painel"] == "https://cortes.exemplo.com"


def test_saude_sem_senha(tmp_path, monkeypatch):
    monkeypatch.setenv("KJCORTES_SENHA", "s")
    cfg = config.carregar(None)
    cfg["pastas"]["dados"] = str(tmp_path / "d")
    c = TestClient(criar_app(cfg, iniciar_fila=False))
    assert c.get("/saude").json() == {"ok": True}
    assert c.get("/").status_code == 401
