"""Carrega a configuração (config.yaml) mesclada com os valores padrão."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

PADRAO: dict[str, Any] = {
    "pastas": {"cache": "cache", "saida": "saida", "dados": "dados"},
    "transcricao": {"modelo": "large-v3", "dispositivo": "auto", "idioma": "pt"},
    "cortes": {"quantidade": 5, "duracao_min": 20, "duracao_max": 60, "intervalo_min": 30},
    "pontuacao": {"audio": 1.0, "chat": 1.5, "fala": 0.5, "ia": 2.0},
    "ia": {"ativa": False, "modelo": "claude-sonnet-5-5", "max_candidatos": 20},
    "video": {"layout": "desfoque", "largura": 1080, "altura": 1920, "encoder": "auto"},
    "legenda": {
        "fonte": "Montserrat ExtraBold",
        "tamanho": 84,
        "palavras_por_linha": 3,
        "cor": "&H00FFFFFF",
        "cor_destaque": "&H0000E5FF",
        "posicao_vertical": 0.70,
    },
}


def _mesclar(base: dict, extra: dict) -> dict:
    for chave, valor in extra.items():
        if isinstance(valor, dict) and isinstance(base.get(chave), dict):
            _mesclar(base[chave], valor)
        else:
            base[chave] = valor
    return base


def carregar(caminho: str | Path | None = None) -> dict[str, Any]:
    """Lê o YAML indicado (ou ./config.yaml, se existir) sobre os valores padrão."""
    cfg = copy.deepcopy(PADRAO)
    arquivo = Path(caminho) if caminho else Path("config.yaml")
    if arquivo.exists():
        with arquivo.open(encoding="utf-8") as f:
            _mesclar(cfg, yaml.safe_load(f) or {})
    elif caminho:
        raise FileNotFoundError(f"Arquivo de configuração não encontrado: {arquivo}")
    return cfg
