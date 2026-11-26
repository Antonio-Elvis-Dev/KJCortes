"""Linha de comando: kjcortes cortar <link ou arquivo>."""

from __future__ import annotations

import argparse
import logging
import sys

from . import __version__, config, pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kjcortes", description="Cortes automáticos de lives e vídeos de streamers")
    parser.add_argument("--version", action="version", version=f"kjcortes {__version__}")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("cortar", help="Gera cortes verticais legendados a partir de um link ou arquivo")
    p.add_argument("entrada", help="Link do YouTube/Twitch ou caminho de um vídeo no disco")
    p.add_argument("-n", "--quantidade", type=int, help="Quantos cortes gerar")
    p.add_argument("-c", "--config", help="Arquivo de configuração (padrão: ./config.yaml)")
    p.add_argument("--canal", default="", help="Nome do streamer para o crédito (padrão: o do vídeo)")
    p.add_argument("--ia", action="store_true", help="Usa a IA (Claude) para avaliar os trechos")
    p.add_argument("--modelo", help="Modelo do Whisper (ex.: small, large-v3)")
    p.add_argument("--layout", choices=["desfoque", "centro"], help="Formato do vídeo vertical")
    p.add_argument("--sem-chat", action="store_true", help="Não baixa o chat da live")
    p.add_argument("--sem-legenda", action="store_true", help="Não grava legendas no vídeo")
    p.add_argument("-v", "--verbose", action="store_true", help="Mostra mais detalhes")

    w = sub.add_parser("painel", help="Abre o painel web (streamers, envio de vídeos e revisão dos cortes)")
    w.add_argument("-c", "--config", help="Arquivo de configuração (padrão: ./config.yaml)")
    w.add_argument("--host", default="127.0.0.1", help="Endereço (padrão: só este computador)")
    w.add_argument("--porta", type=int, default=8000)
    w.add_argument("-v", "--verbose", action="store_true", help="Mostra mais detalhes")

    args = parser.parse_args(argv)
    # No Windows o console usa cp1252 e quebra com emojis dos títulos dos vídeos.
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    cfg = config.carregar(args.config)
    if args.comando == "painel":
        from .web.app import rodar

        import os

        if args.host not in ("127.0.0.1", "localhost") and not os.environ.get("KJCORTES_SENHA"):
            logging.warning("Painel aberto para a rede SEM senha. Defina KJCORTES_SENHA antes de expor na internet.")
        print(f"Painel em http://{'localhost' if args.host == '127.0.0.1' else args.host}:{args.porta}")
        rodar(cfg, args.host, args.porta)
        return 0

    if args.quantidade:
        cfg["cortes"]["quantidade"] = args.quantidade
    if args.ia:
        cfg["ia"]["ativa"] = True
    if args.modelo:
        cfg["transcricao"]["modelo"] = args.modelo
    if args.layout:
        cfg["video"]["layout"] = args.layout

    try:
        cortes = pipeline.executar(args.entrada, cfg, canal=args.canal, usar_chat=not args.sem_chat, legendar=not args.sem_legenda)
    except KeyboardInterrupt:
        return 130
    except Exception as erro:
        logging.error("%s", erro, exc_info=args.verbose)
        return 1

    if not cortes:
        print("Nenhum corte gerado.")
        return 1
    print(f"\n{len(cortes)} cortes gerados em {cortes[0].video.parent}:")
    for c in cortes:
        print(f"  {c.video.name}  {c.candidato.inicio:>8.1f}s  nota {c.candidato.nota:5.2f}  {c.candidato.titulo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
