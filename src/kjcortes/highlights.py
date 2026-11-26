"""Escolha dos trechos mais interessantes do vídeo."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .signals import normalizar
from .transcribe import Segmento

# O chat costuma reagir alguns segundos depois do acontecimento.
ATRASO_CHAT = (3, 12)
MARGEM_INICIO = 0.3
MARGEM_FIM = 0.6


@dataclass
class Candidato:
    inicio: float
    fim: float
    texto: str
    nota: float = 0.0
    componentes: dict[str, float] = field(default_factory=dict)
    titulo: str = ""
    motivo: str = ""

    @property
    def duracao(self) -> float:
        return self.fim - self.inicio


def gerar_janelas(segmentos: list[Segmento], duracao_min: float, duracao_max: float, duracao_video: float) -> list[Candidato]:
    """Cria janelas que começam e terminam em fronteiras de frase, entre duracao_min e duracao_max."""
    janelas: list[Candidato] = []
    if not segmentos:
        # Sem fala detectada: janelas fixas, com metade de sobreposição.
        passo = max(duracao_min, (duracao_min + duracao_max) / 2)
        t = 0.0
        while t + duracao_min <= duracao_video:
            janelas.append(Candidato(t, min(t + passo, duracao_video), ""))
            t += passo / 2
        return janelas

    for i, primeiro in enumerate(segmentos):
        textos = []
        for j in range(i, len(segmentos)):
            s = segmentos[j]
            if s.fim - primeiro.inicio > duracao_max:
                break
            textos.append(s.texto)
            if s.fim - primeiro.inicio >= duracao_min:
                inicio = max(0.0, primeiro.inicio - MARGEM_INICIO)
                fim = min(duracao_video or s.fim + MARGEM_FIM, s.fim + MARGEM_FIM)
                janelas.append(Candidato(inicio, fim, " ".join(textos)))
    return janelas


class _Serie:
    """Série por segundo com médias de intervalo em O(1) via soma acumulada."""

    def __init__(self, valores: np.ndarray):
        self.valores = valores
        self.acum = np.concatenate([[0.0], np.cumsum(valores, dtype=np.float64)])

    def media(self, a: float, b: float) -> float:
        n = len(self.valores)
        i, j = max(0, int(a)), min(n, int(np.ceil(b)))
        if j <= i:
            return 0.0
        return float((self.acum[j] - self.acum[i]) / (j - i))

    def picos(self, a: float, b: float, fracao: float = 0.25) -> float:
        """Média do quarto mais alto do intervalo: valoriza explosões curtas (grito, risada)."""
        n = len(self.valores)
        i, j = max(0, int(a)), min(n, int(np.ceil(b)))
        if j <= i:
            return 0.0
        trecho = np.sort(self.valores[i:j])[::-1]
        k = max(1, int(len(trecho) * fracao))
        return float(trecho[:k].mean())


def pontuar(janelas: list[Candidato], volume: np.ndarray, chat: np.ndarray, fala: np.ndarray, pesos: dict[str, float]) -> None:
    """Dá uma nota a cada janela combinando os sinais normalizados."""
    s_vol = _Serie(normalizar(volume))
    s_chat = _Serie(normalizar(chat)) if chat.size and chat.any() else None
    s_fala = _Serie(normalizar(fala)) if fala.size and fala.any() else None

    for c in janelas:
        comp = {"audio": s_vol.picos(c.inicio, c.fim)}
        if s_chat is not None:
            comp["chat"] = s_chat.picos(c.inicio + ATRASO_CHAT[0], c.fim + ATRASO_CHAT[1])
        if s_fala is not None:
            comp["fala"] = s_fala.media(c.inicio, c.fim)
        c.componentes = comp
        c.nota = sum(pesos.get(k, 0.0) * v for k, v in comp.items())


def selecionar(janelas: list[Candidato], quantidade: int, intervalo_min: float) -> list[Candidato]:
    """Pega as melhores janelas sem sobreposição e com distância mínima entre elas."""
    escolhidas: list[Candidato] = []
    for c in sorted(janelas, key=lambda c: c.nota, reverse=True):
        if len(escolhidas) >= quantidade:
            break
        if all(c.fim + intervalo_min <= e.inicio or c.inicio >= e.fim + intervalo_min for e in escolhidas):
            escolhidas.append(c)
    return escolhidas
