"""Legendas no estilo dos cortes: poucas palavras por vez, palavra falada em destaque."""

from __future__ import annotations

from pathlib import Path

from .transcribe import Palavra, Segmento

PAUSA_QUEBRA = 0.6  # segundos de silêncio que forçam uma nova linha
PONTUACAO_QUEBRA = (".", "!", "?", "…")


def palavras_do_trecho(segmentos: list[Segmento], inicio: float, fim: float) -> list[Palavra]:
    """Palavras dentro do corte, com tempos relativos ao início do corte."""
    saida = []
    for s in segmentos:
        if s.fim < inicio or s.inicio > fim:
            continue
        for p in s.palavras:
            if p.inicio >= inicio and p.fim <= fim + 0.2:
                saida.append(Palavra(max(0.0, p.inicio - inicio), max(0.0, min(fim, p.fim) - inicio), p.texto))
    return saida


def agrupar(palavras: list[Palavra], por_linha: int) -> list[list[Palavra]]:
    grupos: list[list[Palavra]] = []
    atual: list[Palavra] = []
    for p in palavras:
        if atual and (len(atual) >= por_linha or p.inicio - atual[-1].fim > PAUSA_QUEBRA):
            grupos.append(atual)
            atual = []
        atual.append(p)
        if p.texto.endswith(PONTUACAO_QUEBRA):
            grupos.append(atual)
            atual = []
    if atual:
        grupos.append(atual)
    return grupos


def _tempo(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escapar(texto: str) -> str:
    return texto.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def gerar_ass(palavras: list[Palavra], destino: Path, largura: int, altura: int, estilo: dict) -> Path:
    """Escreve o arquivo .ass. Cada linha aparece inteira e a palavra falada muda de cor e cresce."""
    tamanho = int(estilo["tamanho"])
    cor = estilo["cor"]
    destaque = estilo["cor_destaque"]
    x, y = largura // 2, int(altura * float(estilo["posicao_vertical"]))
    contorno = max(2, tamanho // 12)

    linhas = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {largura}",
        f"PlayResY: {altura}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Corte,{estilo['fonte']},{tamanho},{cor},{cor},&H00000000,&H80000000,"
        f"-1,0,0,0,100,100,0,0,1,{contorno},3,5,60,60,0,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    grupos = agrupar(palavras, int(estilo["palavras_por_linha"]))
    for g, grupo in enumerate(grupos):
        fim_grupo = grupo[-1].fim
        if g + 1 < len(grupos):
            # Mantém a linha na tela até a próxima começar, se a pausa for curta.
            prox = grupos[g + 1][0].inicio
            fim_grupo = prox if prox - fim_grupo < PAUSA_QUEBRA else fim_grupo + 0.25
        else:
            fim_grupo += 0.4
        for k, palavra in enumerate(grupo):
            ini = palavra.inicio
            fim = grupo[k + 1].inicio if k + 1 < len(grupo) else fim_grupo
            if fim <= ini:
                continue
            partes = []
            for m, outra in enumerate(grupo):
                txt = _escapar(outra.texto.upper())
                if m == k:
                    partes.append(f"{{\\c{destaque}\\fscx112\\fscy112}}{txt}{{\\c{cor}\\fscx100\\fscy100}}")
                else:
                    partes.append(txt)
            linhas.append(
                f"Dialogue: 0,{_tempo(ini)},{_tempo(fim)},Corte,,0,0,0,,{{\\pos({x},{y})}}" + " ".join(partes)
            )

    destino.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return destino
