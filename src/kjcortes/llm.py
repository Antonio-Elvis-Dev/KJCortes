"""Avaliação opcional dos trechos por IA (Claude): nota de 0 a 10, título e motivo."""

from __future__ import annotations

import json
import logging
import os
import re

from .highlights import Candidato

log = logging.getLogger(__name__)

INSTRUCOES = """Você é editor de cortes de lives para TikTok, Reels e Shorts.
Receberá trechos transcritos de uma live do canal "{canal}" (título: "{titulo}").
Para cada trecho, dê uma nota de 0 a 10 para o potencial de viralizar como corte curto:
humor, reação forte, momento épico, polêmica leve, história com começo e fim, frase marcante.
Penalize trechos sem contexto, conversa morta ou leitura de patrocínio.
Crie também um título curto e chamativo em português (até 60 caracteres, sem hashtags).

Responda APENAS com um array JSON, um objeto por trecho:
[{{"id": 0, "nota": 7, "titulo": "...", "motivo": "uma frase"}}]"""


def avaliar(candidatos: list[Candidato], canal: str, titulo: str, modelo: str, peso: float) -> None:
    """Soma à nota de cada candidato a avaliação da IA. Sem chave de API, não faz nada."""
    if not candidatos:
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        log.warning("ANTHROPIC_API_KEY não definida; pulando a avaliação por IA")
        return
    try:
        import anthropic
    except ImportError:
        log.warning("Pacote anthropic não instalado (pip install 'kjcortes[ia]'); pulando a IA")
        return

    trechos = "\n\n".join(
        f"### Trecho {i} ({c.duracao:.0f}s)\n{c.texto[:2500]}" for i, c in enumerate(candidatos)
    )
    cliente = anthropic.Anthropic()
    try:
        resposta = cliente.messages.create(
            model=modelo,
            max_tokens=4000,
            system=INSTRUCOES.format(canal=canal, titulo=titulo),
            messages=[{"role": "user", "content": trechos}],
        )
    except Exception as erro:
        log.warning("Falha ao chamar a IA: %s", erro)
        return

    texto = "".join(b.text for b in resposta.content if getattr(b, "type", "") == "text")
    for item in interpretar(texto):
        i = item.get("id")
        if isinstance(i, int) and 0 <= i < len(candidatos):
            c = candidatos[i]
            nota = float(item.get("nota", 5))
            c.componentes["ia"] = nota
            # 5 é neutro; cada ponto acima ou abaixo vale meio desvio dos outros sinais.
            c.nota += peso * (nota - 5) / 2
            c.titulo = str(item.get("titulo", ""))[:100]
            c.motivo = str(item.get("motivo", ""))


def interpretar(texto: str) -> list[dict]:
    """Extrai o array JSON da resposta, mesmo se vier dentro de um bloco de código."""
    achado = re.search(r"\[.*\]", texto, re.DOTALL)
    if not achado:
        log.warning("Resposta da IA sem JSON reconhecível")
        return []
    try:
        dados = json.loads(achado.group(0))
    except json.JSONDecodeError:
        log.warning("JSON inválido na resposta da IA")
        return []
    return [d for d in dados if isinstance(d, dict)]
