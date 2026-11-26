"""Banco de dados local (SQLite): streamers, autorizações, vídeos processados e cortes."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

ESQUEMA = """
CREATE TABLE IF NOT EXISTS streamers (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL,
    canal_twitch TEXT DEFAULT '',
    canal_youtube TEXT DEFAULT '',
    arroba_tiktok TEXT DEFAULT '',
    arroba_instagram TEXT DEFAULT '',
    arroba_youtube TEXT DEFAULT '',
    hashtags TEXT DEFAULT '',
    credito_extra TEXT DEFAULT '',
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS autorizacoes (
    id INTEGER PRIMARY KEY,
    streamer_id INTEGER NOT NULL REFERENCES streamers(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL,              -- contrato, mensagem, email, outro
    descricao TEXT DEFAULT '',
    arquivo TEXT DEFAULT '',         -- prova anexada (print, PDF), relativo à pasta de dados
    concedida_em TEXT NOT NULL,      -- AAAA-MM-DD
    valida_ate TEXT DEFAULT '',      -- AAAA-MM-DD, vazio = sem prazo
    revogada INTEGER NOT NULL DEFAULT 0,
    criado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY,
    streamer_id INTEGER NOT NULL REFERENCES streamers(id),
    url TEXT NOT NULL,
    titulo TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'na_fila',   -- na_fila, processando, pronto, erro
    erro TEXT DEFAULT '',
    pasta_saida TEXT DEFAULT '',
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cortes (
    id INTEGER PRIMARY KEY,
    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    streamer_id INTEGER NOT NULL REFERENCES streamers(id),
    numero INTEGER NOT NULL,
    arquivo TEXT NOT NULL,
    inicio REAL NOT NULL,
    fim REAL NOT NULL,
    nota REAL DEFAULT 0,
    titulo TEXT DEFAULT '',
    legenda_tiktok TEXT DEFAULT '',
    legenda_instagram TEXT DEFAULT '',
    titulo_youtube TEXT DEFAULT '',
    descricao_youtube TEXT DEFAULT '',
    link_original TEXT DEFAULT '',
    transcricao TEXT DEFAULT '',
    metadados TEXT DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pendente',  -- pendente, aprovado, rejeitado
    revisado_em TEXT DEFAULT '',
    criado_em TEXT NOT NULL
);
"""

STATUS_CORTE = ("pendente", "aprovado", "rejeitado")


def agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Banco:
    def __init__(self, caminho: str | Path):
        self.caminho = Path(caminho)
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with self.conexao() as c:
            c.executescript(ESQUEMA)

    @contextmanager
    def conexao(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.caminho, timeout=30)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def _um(self, sql: str, *args) -> dict | None:
        with self.conexao() as c:
            r = c.execute(sql, args).fetchone()
        return dict(r) if r else None

    def _todos(self, sql: str, *args) -> list[dict]:
        with self.conexao() as c:
            return [dict(r) for r in c.execute(sql, args).fetchall()]

    def _inserir(self, tabela: str, dados: dict) -> int:
        cols = ", ".join(dados)
        marcas = ", ".join("?" for _ in dados)
        with self.conexao() as c:
            return c.execute(f"INSERT INTO {tabela} ({cols}) VALUES ({marcas})", tuple(dados.values())).lastrowid

    def _atualizar(self, tabela: str, ident: int, dados: dict) -> None:
        if not dados:
            return
        sets = ", ".join(f"{k} = ?" for k in dados)
        with self.conexao() as c:
            c.execute(f"UPDATE {tabela} SET {sets} WHERE id = ?", (*dados.values(), ident))

    # Streamers ---------------------------------------------------------------

    CAMPOS_STREAMER = ("nome", "canal_twitch", "canal_youtube", "arroba_tiktok", "arroba_instagram",
                       "arroba_youtube", "hashtags", "credito_extra", "ativo")

    def criar_streamer(self, **dados: Any) -> int:
        d = {k: dados.get(k, "") for k in self.CAMPOS_STREAMER if k != "ativo"}
        if not d["nome"].strip():
            raise ValueError("O nome do streamer é obrigatório")
        for k in ("arroba_tiktok", "arroba_instagram", "arroba_youtube"):
            d[k] = normalizar_arroba(d[k])
        d["ativo"] = 1 if dados.get("ativo", True) else 0
        d["criado_em"] = agora()
        return self._inserir("streamers", d)

    def atualizar_streamer(self, ident: int, **dados: Any) -> None:
        d = {k: v for k, v in dados.items() if k in self.CAMPOS_STREAMER}
        for k in ("arroba_tiktok", "arroba_instagram", "arroba_youtube"):
            if k in d:
                d[k] = normalizar_arroba(d[k])
        if "ativo" in d:
            d["ativo"] = 1 if d["ativo"] else 0
        self._atualizar("streamers", ident, d)

    def streamer(self, ident: int) -> dict | None:
        return self._um("SELECT * FROM streamers WHERE id = ?", ident)

    def streamers(self) -> list[dict]:
        lista = self._todos("SELECT * FROM streamers ORDER BY nome COLLATE NOCASE")
        for s in lista:
            s["autorizado"] = self.autorizacao_valida(s["id"]) is not None
        return lista

    def streamer_por_canal(self, url_canal: str) -> dict | None:
        alvo = normalizar_canal(url_canal)
        if not alvo:
            return None
        for s in self._todos("SELECT * FROM streamers"):
            if alvo in (normalizar_canal(s["canal_twitch"]), normalizar_canal(s["canal_youtube"])):
                return s
        return None

    # Autorizações -------------------------------------------------------------

    def criar_autorizacao(self, streamer_id: int, tipo: str, concedida_em: str, descricao: str = "",
                          arquivo: str = "", valida_ate: str = "") -> int:
        date.fromisoformat(concedida_em)
        if valida_ate:
            date.fromisoformat(valida_ate)
        return self._inserir("autorizacoes", {
            "streamer_id": streamer_id, "tipo": tipo, "descricao": descricao, "arquivo": arquivo,
            "concedida_em": concedida_em, "valida_ate": valida_ate, "criado_em": agora(),
        })

    def revogar_autorizacao(self, ident: int) -> None:
        self._atualizar("autorizacoes", ident, {"revogada": 1})

    def autorizacoes(self, streamer_id: int) -> list[dict]:
        return self._todos("SELECT * FROM autorizacoes WHERE streamer_id = ? ORDER BY concedida_em DESC", streamer_id)

    def autorizacao(self, ident: int) -> dict | None:
        return self._um("SELECT * FROM autorizacoes WHERE id = ?", ident)

    def autorizacao_valida(self, streamer_id: int, hoje: date | None = None) -> dict | None:
        """A autorização vigente do streamer, ou None. Streamer inativo nunca está autorizado."""
        s = self.streamer(streamer_id)
        if not s or not s["ativo"]:
            return None
        hoje_txt = (hoje or date.today()).isoformat()
        return self._um(
            "SELECT * FROM autorizacoes WHERE streamer_id = ? AND revogada = 0 AND concedida_em <= ? "
            "AND (valida_ate = '' OR valida_ate >= ?) ORDER BY concedida_em DESC LIMIT 1",
            streamer_id, hoje_txt, hoje_txt,
        )

    # Vídeos e cortes ---------------------------------------------------------

    def criar_video(self, streamer_id: int, url: str) -> int:
        t = agora()
        return self._inserir("videos", {"streamer_id": streamer_id, "url": url, "criado_em": t, "atualizado_em": t})

    def atualizar_video(self, ident: int, **dados: Any) -> None:
        dados["atualizado_em"] = agora()
        self._atualizar("videos", ident, dados)

    def video(self, ident: int) -> dict | None:
        return self._um("SELECT * FROM videos WHERE id = ?", ident)

    def videos(self, limite: int = 50) -> list[dict]:
        return self._todos(
            "SELECT v.*, s.nome AS streamer_nome, "
            "(SELECT COUNT(*) FROM cortes c WHERE c.video_id = v.id) AS total_cortes "
            "FROM videos v JOIN streamers s ON s.id = v.streamer_id ORDER BY v.id DESC LIMIT ?", limite)

    def criar_corte(self, **dados: Any) -> int:
        if isinstance(dados.get("metadados"), dict):
            dados["metadados"] = json.dumps(dados["metadados"], ensure_ascii=False)
        dados["criado_em"] = agora()
        return self._inserir("cortes", dados)

    CAMPOS_EDITAVEIS = ("titulo", "legenda_tiktok", "legenda_instagram", "titulo_youtube", "descricao_youtube")

    def editar_corte(self, ident: int, **dados: Any) -> None:
        self._atualizar("cortes", ident, {k: v for k, v in dados.items() if k in self.CAMPOS_EDITAVEIS})

    def revisar_corte(self, ident: int, status: str) -> None:
        if status not in STATUS_CORTE:
            raise ValueError(f"Status inválido: {status}")
        self._atualizar("cortes", ident, {"status": status, "revisado_em": agora() if status != "pendente" else ""})

    def corte(self, ident: int) -> dict | None:
        return self._um(
            "SELECT c.*, s.nome AS streamer_nome, v.url AS video_url, v.titulo AS video_titulo "
            "FROM cortes c JOIN streamers s ON s.id = c.streamer_id JOIN videos v ON v.id = c.video_id "
            "WHERE c.id = ?", ident)

    def cortes(self, status: str | None = None, video_id: int | None = None) -> list[dict]:
        sql = ("SELECT c.*, s.nome AS streamer_nome FROM cortes c JOIN streamers s ON s.id = c.streamer_id WHERE 1=1")
        args: list[Any] = []
        if status:
            sql += " AND c.status = ?"
            args.append(status)
        if video_id:
            sql += " AND c.video_id = ?"
            args.append(video_id)
        return self._todos(sql + " ORDER BY c.id DESC", *args)

    def contagem_cortes(self) -> dict[str, int]:
        linhas = self._todos("SELECT status, COUNT(*) AS n FROM cortes GROUP BY status")
        base = {s: 0 for s in STATUS_CORTE}
        base.update({l["status"]: l["n"] for l in linhas})
        return base


def normalizar_arroba(valor: str) -> str:
    """'@Fulano', 'fulano', 'https://www.tiktok.com/@fulano' -> 'fulano'."""
    v = (valor or "").strip()
    if "/" in v:
        partes = [p for p in urlparse(v if "://" in v else "https://" + v).path.split("/") if p]
        v = partes[0] if partes else ""
    return v.lstrip("@").strip()


def normalizar_canal(url: str) -> str:
    """Reduz o link de um canal a 'dominio/caminho' em minúsculas, para comparação."""
    u = (url or "").strip().lower()
    if not u:
        return ""
    p = urlparse(u if "://" in u else "https://" + u)
    host = p.netloc.removeprefix("www.").removeprefix("m.")
    caminho = p.path.rstrip("/")
    for sufixo in ("/videos", "/featured", "/streams", "/about", "/live"):
        caminho = caminho.removesuffix(sufixo)
    return f"{host}{caminho}"
