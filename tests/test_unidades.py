import numpy as np

from kjcortes import config, highlights, llm, render, subtitles
from kjcortes.highlights import Candidato
from kjcortes.transcribe import Palavra, Segmento


def seg(inicio, fim, texto):
    palavras = texto.split()
    passo = (fim - inicio) / len(palavras)
    return Segmento(inicio, fim, texto, [Palavra(inicio + i * passo, inicio + (i + 1) * passo, p) for i, p in enumerate(palavras)])


def test_config_mescla_padrao(tmp_path):
    arq = tmp_path / "c.yaml"
    arq.write_text("cortes:\n  quantidade: 2\n")
    cfg = config.carregar(arq)
    assert cfg["cortes"]["quantidade"] == 2
    assert cfg["cortes"]["duracao_max"] == 60


def test_janelas_respeitam_duracao():
    segs = [seg(i * 10, i * 10 + 9, f"frase numero {i}") for i in range(20)]
    janelas = highlights.gerar_janelas(segs, 20, 60, 200)
    assert janelas
    for j in janelas:
        assert 19 <= j.duracao <= 61.5


def test_janelas_sem_fala():
    janelas = highlights.gerar_janelas([], 20, 60, 300)
    assert janelas and all(j.fim <= 300 for j in janelas)


def test_pontuar_prefere_pico_de_volume_e_chat():
    volume = np.full(300, -30.0)
    volume[150:160] = -5.0
    chat = np.zeros(300)
    chat[155:170] = 20
    janelas = [Candidato(0, 30, ""), Candidato(140, 170, ""), Candidato(250, 280, "")]
    highlights.pontuar(janelas, volume, chat, np.zeros(0), {"audio": 1, "chat": 1.5})
    assert max(janelas, key=lambda c: c.nota).inicio == 140


def test_selecionar_sem_sobreposicao():
    janelas = [Candidato(0, 30, "", nota=5), Candidato(10, 40, "", nota=4), Candidato(100, 130, "", nota=3)]
    escolhidas = highlights.selecionar(janelas, 3, 10)
    assert [c.inicio for c in escolhidas] == [0, 100]


def test_palavras_relativas_ao_corte():
    segs = [seg(100, 104, "ola tudo bem pessoal")]
    palavras = subtitles.palavras_do_trecho(segs, 99, 110)
    assert palavras[0].texto == "ola" and abs(palavras[0].inicio - 1) < 1e-6


def test_agrupar_quebra_por_pontuacao_e_tamanho():
    ps = [Palavra(i * 0.3, i * 0.3 + 0.25, t) for i, t in enumerate("isso foi incrível! olha só isso aqui".split())]
    grupos = subtitles.agrupar(ps, 3)
    assert [len(g) for g in grupos] == [3, 3, 1]


def test_gerar_ass(tmp_path):
    ps = [Palavra(0.0, 0.4, "ola"), Palavra(0.4, 0.8, "{mundo}")]
    arq = subtitles.gerar_ass(ps, tmp_path / "x.ass", 1080, 1920, config.PADRAO["legenda"])
    texto = arq.read_text()
    assert "PlayResY: 1920" in texto
    assert texto.count("Dialogue:") == 2
    assert "(MUNDO)" in texto  # chaves escapadas para não virar tag ASS


def test_filtro_video():
    f = render.filtro_video("desfoque", 1080, 1920, "c.ass")
    assert f.startswith("[0:v]split") and "ass=c.ass" in f and f.endswith("[v]")
    assert "crop=1080:1920" in render.filtro_video("centro", 1080, 1920, None)


def test_interpretar_resposta_ia():
    texto = 'Aqui:\n```json\n[{"id": 0, "nota": 8, "titulo": "Grito épico"}]\n```'
    assert llm.interpretar(texto)[0]["nota"] == 8
    assert llm.interpretar("sem json") == []


def test_ler_wav_para_whisper(tmp_path):
    import subprocess
    import wave

    from kjcortes import signals, transcribe

    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=d=2", str(video)], check=True)
    wav = signals.extrair_audio(video, tmp_path / "a.wav")
    amostras = transcribe.ler_wav(wav)
    assert amostras.dtype == np.float32 and abs(len(amostras) - 32000) < 2000
    assert 0 < np.abs(amostras).max() <= 1
