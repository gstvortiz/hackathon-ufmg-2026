"""
JurisIA - Analisador Estrategico de Processos
MVP para Hackathon Juridico

Arquitetura: Flask + document_extractor.py + placeholders estatisticos
"""

from __future__ import annotations

import importlib
import json
import logging
import math
import os
import shutil
import sqlite3
import sys
import tempfile
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request
from werkzeug.utils import secure_filename

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

try:
    from .document_extractor import (
        classify_document,
        extract_numero_processo,
        extract_uf,
        extract_valor_causa,
        read_pdf_text,
    )
except ImportError:
    from document_extractor import (
        classify_document,
        extract_numero_processo,
        extract_uf,
        extract_valor_causa,
        read_pdf_text,
    )

# ---------------------------------------------------------------------------
# Configuracao da Aplicacao
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB por upload
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "juris-ia-hackathon-2024")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = os.environ.get(
    "JURIS_DB_PATH",
    str(Path(__file__).resolve().with_name("juris_ia.db")),
)
PENDING_ANALISE_TTL_SECONDS = int(os.environ.get("PENDING_ANALISE_TTL_SECONDS", "7200"))
MAX_PENDING_ANALISES = int(os.environ.get("MAX_PENDING_ANALISES", "500"))


def _descobrir_raiz_projeto(start: Path) -> Path | None:
    for candidate in [start.parent, *start.parents]:
        if (
            (candidate / "src" / "policy" / "app" / "inference.py").exists()
            and (candidate / "src" / "utils").exists()
        ):
            return candidate
    return None


PROJECT_ROOT = _descobrir_raiz_projeto(Path(__file__).resolve())
if PROJECT_ROOT is not None:
    root_str = str(PROJECT_ROOT)
    if root_str not in sys.path:
        sys.path.append(root_str)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS analises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    criado_em TEXT NOT NULL,
    numero_processo TEXT,
    uf TEXT,
    valor_causa REAL,
    recomendacao_ia TEXT NOT NULL,
    e_vp_acordo REAL NOT NULL,
    e_vp_defesa REAL NOT NULL,
    valor_sugerido_acordo REAL,
    p_exito REAL NOT NULL,
    docs_presentes TEXT NOT NULL,
    docs_faltantes TEXT NOT NULL,
    docs_binarios TEXT NOT NULL,
    desfecho_real TEXT,
    valor_real REAL,
    aderiu_recomend INTEGER
);
"""

SCHEMA_FEEDBACK_SQL = """
CREATE TABLE IF NOT EXISTS analises_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    analise_id INTEGER NOT NULL UNIQUE,
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL,
    advogado_seguiu INTEGER,
    desfecho_real TEXT,
    valor_pago REAL,
    modelo_acertou INTEGER,
    observacoes TEXT,
    FOREIGN KEY (analise_id) REFERENCES analises(id)
);
"""

SCHEMA_PENDENTES_SQL = """
CREATE TABLE IF NOT EXISTS analises_pendentes (
    token TEXT PRIMARY KEY,
    criado_em TEXT NOT NULL,
    expira_em TEXT NOT NULL,
    payload_analise TEXT NOT NULL
);
"""

COLUNAS_ESPERADAS_ANALISES = {
    "numero_processo": "TEXT",
    "docs_binarios": "TEXT",
    "desfecho_real": "TEXT",
    "valor_real": "REAL",
    "aderiu_recomend": "INTEGER",
    "valor_sugerido_acordo": "REAL",
}

COLUNAS_ESPERADAS_FEEDBACK = {
    "valor_pago": "REAL",
}


# ---------------------------------------------------------------------------
# Mapeamentos de documentos
# ---------------------------------------------------------------------------

DOCUMENTOS_OBRIGATORIOS = ["autos"]
DOCUMENTOS_OPCIONAIS = ["contrato", "extrato", "comprovante", "dossie", "demonstrativo", "laudo"]
TODOS_DOCUMENTOS = DOCUMENTOS_OBRIGATORIOS + DOCUMENTOS_OPCIONAIS

CAMPO_PARA_CLASSE_EXTRATOR = {
    "autos": "autos",
    "contrato": "contrato",
    "extrato": "extrato",
    "comprovante": "comprovante_credito",
    "dossie": "dossie",
    "demonstrativo": "demonstrativo_divida",
    "laudo": "laudo_referenciado",
}

CLASSE_EXTRATOR_PARA_INTERNO = {
    "autos": "autos",
    "contrato": "contrato",
    "extrato": "extrato",
    "comprovante_credito": "comprovante",
    "dossie": "dossie",
    "demonstrativo_divida": "demonstrativo",
    "laudo_referenciado": "laudo",
}

ROTULO_CLASSE = {
    "autos": "Autos",
    "contrato": "Contrato",
    "extrato": "Extrato",
    "comprovante_credito": "Comprovante de credito",
    "dossie": "Dossie",
    "demonstrativo_divida": "Demonstrativo de divida",
    "laudo_referenciado": "Laudo referenciado",
    "unknown": "Nao identificado",
}


# ---------------------------------------------------------------------------
# Banco de dados
# ---------------------------------------------------------------------------


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def garantir_colunas(conn: sqlite3.Connection, tabela: str, colunas_esperadas: dict[str, str]) -> None:
    existentes = {row["name"] for row in conn.execute(f"PRAGMA table_info({tabela})").fetchall()}
    for coluna, tipo in colunas_esperadas.items():
        if coluna not in existentes:
            conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
    conn.commit()


def conectar_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(SCHEMA_SQL)
    conn.execute(SCHEMA_FEEDBACK_SQL)
    conn.execute(SCHEMA_PENDENTES_SQL)
    garantir_colunas(conn, "analises", COLUNAS_ESPERADAS_ANALISES)
    garantir_colunas(conn, "analises_feedback", COLUNAS_ESPERADAS_FEEDBACK)
    conn.commit()
    sincronizar_feedback_pendente(conn)
    limpar_analises_pendentes_db(conn)
    return conn


def inicializar_banco() -> None:
    conn = conectar_db()
    conn.close()


def sincronizar_feedback_pendente(conn: sqlite3.Connection) -> None:
    agora = utc_now_iso()
    conn.execute(
        """
        INSERT INTO analises_feedback (analise_id, criado_em, atualizado_em)
        SELECT a.id, ?, ?
        FROM analises a
        LEFT JOIN analises_feedback f ON f.analise_id = a.id
        WHERE f.analise_id IS NULL
        """,
        (agora, agora),
    )
    conn.commit()


def registrar_analise(
    numero_processo: str | None,
    uf: str | None,
    valor_causa: float,
    recomendacao: str,
    valor_acordo: float,
    valor_defesa: float,
    valor_sugerido_acordo: float | None,
    p_exito: float,
    docs_presentes: list[str],
    docs_faltantes: list[str],
    docs_binarios: dict[str, int],
) -> int:
    conn = conectar_db()
    cursor = conn.execute(
        """
        INSERT INTO analises (
            criado_em,
            numero_processo,
            uf,
            valor_causa,
            recomendacao_ia,
            e_vp_acordo,
            e_vp_defesa,
            valor_sugerido_acordo,
            p_exito,
            docs_presentes,
            docs_faltantes,
            docs_binarios
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            utc_now_iso(),
            numero_processo,
            uf,
            valor_causa,
            recomendacao,
            valor_acordo,
            valor_defesa,
            valor_sugerido_acordo,
            p_exito,
            json.dumps(docs_presentes, ensure_ascii=False),
            json.dumps(docs_faltantes, ensure_ascii=False),
            json.dumps(docs_binarios, ensure_ascii=False),
        ),
    )
    analise_id = int(cursor.lastrowid)
    agora = utc_now_iso()
    conn.execute(
        """
        INSERT INTO analises_feedback (analise_id, criado_em, atualizado_em)
        VALUES (?, ?, ?)
        ON CONFLICT(analise_id) DO NOTHING
        """,
        (analise_id, agora, agora),
    )
    conn.commit()
    conn.close()
    return analise_id


def registrar_feedback_analise(
    analise_id: int,
    advogado_seguiu: int | None,
    desfecho_real: str | None,
    valor_pago: float | None,
    observacoes: str | None,
) -> dict[str, Any]:
    conn = conectar_db()
    analise = conn.execute(
        "SELECT id, recomendacao_ia FROM analises WHERE id = ?",
        (analise_id,),
    ).fetchone()
    if not analise:
        conn.close()
        raise ValueError("Analise nao encontrada.")

    recomendacao = analise["recomendacao_ia"]
    modelo_acertou = None
    if desfecho_real:
        modelo_acertou = int(desfecho_real == recomendacao)

    agora = utc_now_iso()
    conn.execute(
        """
        INSERT INTO analises_feedback (
            analise_id,
            criado_em,
            atualizado_em,
            advogado_seguiu,
            desfecho_real,
            valor_pago,
            modelo_acertou,
            observacoes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(analise_id) DO UPDATE SET
            atualizado_em=excluded.atualizado_em,
            advogado_seguiu=excluded.advogado_seguiu,
            desfecho_real=excluded.desfecho_real,
            valor_pago=excluded.valor_pago,
            modelo_acertou=excluded.modelo_acertou,
            observacoes=excluded.observacoes
        """,
        (
            analise_id,
            agora,
            agora,
            advogado_seguiu,
            desfecho_real,
            valor_pago,
            modelo_acertou,
            observacoes,
        ),
    )

    # Espelha os campos legados para manter compatibilidade com consultas antigas.
    conn.execute(
        """
        UPDATE analises
        SET aderiu_recomend = ?, desfecho_real = ?, valor_real = ?
        WHERE id = ?
        """,
        (advogado_seguiu, desfecho_real, valor_pago, analise_id),
    )

    conn.commit()
    conn.close()
    return {
        "analise_id": analise_id,
        "recomendacao_ia": recomendacao,
        "desfecho_real": desfecho_real,
        "valor_pago": valor_pago,
        "modelo_acertou": modelo_acertou,
    }


def atualizar_dados_analise(analise_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Atualiza campos da tabela `analises` para um registro especifico.
    Permite update parcial (somente campos enviados no payload).
    """
    campos: dict[str, Any] = {}

    if "numero_processo" in payload:
        numero_processo = payload.get("numero_processo")
        if numero_processo is None:
            campos["numero_processo"] = None
        else:
            numero_processo = str(numero_processo).strip()
            campos["numero_processo"] = numero_processo or None

    if "uf" in payload:
        uf = payload.get("uf")
        if uf is None:
            campos["uf"] = None
        else:
            uf = str(uf).strip().upper()
            if uf and (len(uf) != 2 or not uf.isalpha()):
                raise ValueError("Campo 'uf' deve ter 2 letras (ex: SP) ou null.")
            campos["uf"] = uf or None

    if "valor_causa" in payload:
        valor_causa = payload.get("valor_causa")
        if valor_causa is None:
            campos["valor_causa"] = None
        else:
            try:
                valor_causa = float(valor_causa)
            except (ValueError, TypeError):
                raise ValueError("Campo 'valor_causa' deve ser numero > 0 ou null.") from None
            if not math.isfinite(valor_causa):
                raise ValueError("Campo 'valor_causa' deve ser numero > 0 ou null.")
            if valor_causa <= 0:
                raise ValueError("Campo 'valor_causa' deve ser numero > 0 ou null.")
            campos["valor_causa"] = valor_causa

    recomendacao_payload = payload.get("recomendacao_ia", payload.get("recomendacao"))
    if "recomendacao_ia" in payload or "recomendacao" in payload:
        if recomendacao_payload is None:
            raise ValueError("Campo 'recomendacao_ia' nao pode ser null.")
        recomendacao_payload = str(recomendacao_payload).strip().upper()
        if recomendacao_payload not in {"ACORDO", "DEFESA"}:
            raise ValueError("Campo 'recomendacao_ia' deve ser 'ACORDO' ou 'DEFESA'.")
        campos["recomendacao_ia"] = recomendacao_payload

    for nome in ("e_vp_acordo", "e_vp_defesa", "valor_sugerido_acordo"):
        if nome in payload:
            valor = payload.get(nome)
            if valor is None:
                if nome in {"e_vp_acordo", "e_vp_defesa"}:
                    raise ValueError(f"Campo '{nome}' nao pode ser null.")
                campos[nome] = None
            else:
                try:
                    valor = float(valor)
                except (ValueError, TypeError):
                    raise ValueError(f"Campo '{nome}' deve ser numero >= 0 ou null.") from None
                if not math.isfinite(valor):
                    raise ValueError(f"Campo '{nome}' deve ser numero >= 0 ou null.")
                if valor < 0:
                    raise ValueError(f"Campo '{nome}' deve ser numero >= 0 ou null.")
                campos[nome] = valor

    if "p_exito" in payload:
        p_exito = payload.get("p_exito")
        if p_exito is None:
            raise ValueError("Campo 'p_exito' nao pode ser null.")
        else:
            try:
                p_exito = float(p_exito)
            except (ValueError, TypeError):
                raise ValueError("Campo 'p_exito' deve ser numero entre 0 e 1 ou null.") from None
            if not math.isfinite(p_exito):
                raise ValueError("Campo 'p_exito' deve ser numero entre 0 e 1 ou null.")
            if not (0 <= p_exito <= 1):
                raise ValueError("Campo 'p_exito' deve ser numero entre 0 e 1 ou null.")
            campos["p_exito"] = p_exito

    if not campos:
        return {"analise_id": analise_id, "campos_atualizados": []}

    conn = conectar_db()
    row = conn.execute("SELECT id FROM analises WHERE id = ?", (analise_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError("Analise nao encontrada.")

    set_sql = ", ".join(f"{coluna} = ?" for coluna in campos)
    valores = list(campos.values()) + [analise_id]
    conn.execute(f"UPDATE analises SET {set_sql} WHERE id = ?", valores)
    conn.commit()
    conn.close()

    return {"analise_id": analise_id, "campos_atualizados": list(campos.keys())}


def limpar_analises_pendentes_db(conn: sqlite3.Connection) -> None:
    agora = utc_now_iso()
    conn.execute("DELETE FROM analises_pendentes WHERE expira_em < ?", (agora,))

    total = conn.execute("SELECT COUNT(*) AS c FROM analises_pendentes").fetchone()["c"]
    if total > MAX_PENDING_ANALISES:
        excesso = total - MAX_PENDING_ANALISES
        conn.execute(
            """
            DELETE FROM analises_pendentes
            WHERE token IN (
                SELECT token
                FROM analises_pendentes
                ORDER BY criado_em ASC
                LIMIT ?
            )
            """,
            (excesso,),
        )
    conn.commit()


def criar_analise_pendente(payload_analise: dict[str, Any]) -> str:
    token = uuid.uuid4().hex
    criado_em = utc_now_iso()
    expira_em = (datetime.utcnow() + timedelta(seconds=PENDING_ANALISE_TTL_SECONDS)).replace(microsecond=0).isoformat() + "Z"

    conn = conectar_db()
    limpar_analises_pendentes_db(conn)
    conn.execute(
        """
        INSERT INTO analises_pendentes (token, criado_em, expira_em, payload_analise)
        VALUES (?, ?, ?, ?)
        """,
        (
            token,
            criado_em,
            expira_em,
            json.dumps(payload_analise, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()
    return token


def calcular_metricas_gerenciais(conn: sqlite3.Connection) -> dict[str, Any]:
    total = conn.execute("SELECT COUNT(*) AS total FROM analises").fetchone()["total"]

    com_feedback = conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM analises_feedback
        WHERE advogado_seguiu IS NOT NULL
           OR desfecho_real IS NOT NULL
           OR valor_pago IS NOT NULL
        """
    ).fetchone()["c"]

    com_desfecho = conn.execute(
        "SELECT COUNT(*) AS c FROM analises_feedback WHERE desfecho_real IS NOT NULL"
    ).fetchone()["c"]

    taxa_aderencia = conn.execute(
        """
        SELECT AVG(CAST(advogado_seguiu AS REAL)) AS taxa
        FROM analises_feedback
        WHERE advogado_seguiu IS NOT NULL
        """
    ).fetchone()["taxa"]

    acuracia = conn.execute(
        """
        SELECT AVG(CAST(modelo_acertou AS REAL)) AS taxa
        FROM analises_feedback
        WHERE modelo_acertou IS NOT NULL
        """
    ).fetchone()["taxa"]

    rows_fin = conn.execute(
        """
        SELECT
            a.recomendacao_ia,
            a.e_vp_acordo,
            a.e_vp_defesa,
            f.valor_pago AS valor_observado
        FROM analises a
        JOIN analises_feedback f ON f.analise_id = a.id
        WHERE f.valor_pago IS NOT NULL
        """
    ).fetchall()
    if rows_fin:
        erros = []
        for row in rows_fin:
            esperado = row["e_vp_acordo"] if row["recomendacao_ia"] == "ACORDO" else row["e_vp_defesa"]
            erros.append(abs(esperado - row["valor_observado"]))
        mae = round(sum(erros) / len(erros), 2)
        rmse = round(math.sqrt(sum(e * e for e in erros) / len(erros)), 2)
    else:
        mae = None
        rmse = None

    rec_dist_rows = conn.execute(
        "SELECT recomendacao_ia, COUNT(*) AS n FROM analises GROUP BY recomendacao_ia"
    ).fetchall()
    rec_dist = {row["recomendacao_ia"]: row["n"] for row in rec_dist_rows}

    top_ufs_rows = conn.execute(
        "SELECT uf, COUNT(*) AS n FROM analises WHERE uf IS NOT NULL GROUP BY uf ORDER BY n DESC LIMIT 5"
    ).fetchall()
    top_ufs = {row["uf"]: row["n"] for row in top_ufs_rows}

    medias = conn.execute(
        "SELECT AVG(valor_causa) AS vc, AVG(p_exito) AS pe FROM analises"
    ).fetchone()

    periodo = conn.execute(
        "SELECT MIN(criado_em) AS ini, MAX(criado_em) AS fim FROM analises"
    ).fetchone()

    economia_rows = conn.execute(
        """
        SELECT
            a.recomendacao_ia,
            a.e_vp_acordo,
            a.e_vp_defesa,
            f.valor_pago
        FROM analises a
        JOIN analises_feedback f ON f.analise_id = a.id
        WHERE f.valor_pago IS NOT NULL
        """
    ).fetchall()

    economias_modelo: list[float] = []
    economias_vs_recomendado: list[float] = []
    valor_total_pago = 0.0
    valor_total_contrafactual = 0.0

    for row in economia_rows:
        valor_pago = float(row["valor_pago"])
        valor_total_pago += valor_pago

        if row["recomendacao_ia"] == "ACORDO":
            esperado_recomendado = float(row["e_vp_acordo"])
            esperado_contrafactual = float(row["e_vp_defesa"])
        else:
            esperado_recomendado = float(row["e_vp_defesa"])
            esperado_contrafactual = float(row["e_vp_acordo"])

        valor_total_contrafactual += esperado_contrafactual
        economias_modelo.append(esperado_contrafactual - valor_pago)
        economias_vs_recomendado.append(esperado_recomendado - valor_pago)

    economia_total_modelo = round(sum(economias_modelo), 2) if economias_modelo else None
    economia_media_modelo = round(sum(economias_modelo) / len(economias_modelo), 2) if economias_modelo else None
    economia_mediana_modelo = round(float(sorted(economias_modelo)[len(economias_modelo) // 2]), 2) if economias_modelo else None

    economia_total_vs_recomendado = round(sum(economias_vs_recomendado), 2) if economias_vs_recomendado else None
    economia_media_vs_recomendado = (
        round(sum(economias_vs_recomendado) / len(economias_vs_recomendado), 2)
        if economias_vs_recomendado
        else None
    )

    casos_economia_positiva = sum(1 for e in economias_modelo if e > 0)
    taxa_casos_economia = round((casos_economia_positiva / len(economias_modelo)) * 100, 2) if economias_modelo else None
    economia_percentual_modelo = (
        round(((valor_total_contrafactual - valor_total_pago) / valor_total_contrafactual) * 100, 2)
        if valor_total_contrafactual > 0
        else None
    )

    return {
        "total_analises": total,
        "com_feedback": com_feedback,
        "com_desfecho": com_desfecho,
        "taxa_aderencia": round((taxa_aderencia or 0) * 100, 2),
        "acuracia_recomendacao": round((acuracia or 0) * 100, 2),
        "mae_financeiro": mae,
        "rmse_financeiro": rmse,
        "distribuicao_rec": rec_dist,
        "distribuicao_uf_top5": top_ufs,
        "pagamentos_registrados": len(economias_modelo),
        "valor_total_pago": round(valor_total_pago, 2) if economias_modelo else None,
        "valor_total_cenario_sem_modelo": round(valor_total_contrafactual, 2) if economias_modelo else None,
        "economia_total_modelo": economia_total_modelo,
        "economia_media_modelo": economia_media_modelo,
        "economia_mediana_modelo": economia_mediana_modelo,
        "economia_percentual_modelo": economia_percentual_modelo,
        "casos_economia_positiva": casos_economia_positiva,
        "taxa_casos_economia_positiva": taxa_casos_economia,
        "economia_total_vs_previsto_recomendacao": economia_total_vs_recomendado,
        "economia_media_vs_previsto_recomendacao": economia_media_vs_recomendado,
        "valor_causa_medio": round(medias["vc"] or 0, 2),
        "p_exito_medio": round(medias["pe"] or 0, 4),
        "periodo": {"inicio": periodo["ini"], "fim": periodo["fim"]},
    }


def gerar_relatorio_openai(metricas: dict[str, Any]) -> tuple[str, str]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY nao encontrada. Configure a chave no .env ou no ambiente do servidor."
        )

    try:
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError(
            "Pacote 'openai' nao instalado. Rode: pip install -r src/interface/requirements_web.txt"
        ) from exc

    model = os.environ.get("OPENAI_REPORT_MODEL", "gpt-4o-mini")
    client = OpenAI(api_key=api_key)

    system_prompt = (
        "Voce e um analista senior de jurimetria. Gere um relatorio executivo em portugues, "
        "claro e acionavel sobre a eficacia do modelo JurisIA com base nas metricas fornecidas. "
        "Inclua: resumo executivo, pontos fortes, riscos, 3 acoes priorizadas, "
        "avaliacao de economia do modelo com base no cenario sem modelo (contrafactual) "
        "versus valor efetivamente pago. Responda em Markdown."
    )
    user_prompt = (
        "Analise as metricas abaixo (extraidas das tabelas analises e analises_feedback) "
        "e gere o relatorio:\n\n"
        + json.dumps(metricas, ensure_ascii=False, indent=2)
    )

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=1000,
    )
    texto = (response.choices[0].message.content or "").strip()
    if not texto:
        raise RuntimeError("A API retornou resposta vazia para o relatorio.")
    return texto, model


# ---------------------------------------------------------------------------
# MÓDULO 1 — Processamento de Documentos
# ---------------------------------------------------------------------------


def _salvar_upload_temporario(arquivo, pasta_tmp: Path) -> Path:
    nome_seguro = secure_filename(arquivo.filename) or "arquivo.pdf"
    caminho = pasta_tmp / nome_seguro
    arquivo.stream.seek(0)
    arquivo.save(caminho)
    return caminho


def _carregar_arquivos_recebidos(arquivos) -> list[tuple[str, Any]]:
    recebidos: list[tuple[str, Any]] = []
    for campo in CAMPO_PARA_CLASSE_EXTRATOR:
        for arquivo in arquivos.getlist(campo):
            if arquivo and arquivo.filename:
                recebidos.append((campo, arquivo))
    return recebidos


def validar_documentos(arquivos) -> dict[str, Any]:
    """
    Valida classe documental e detecta duplicidade por tipo.

    Regras:
    - Todos os uploads devem ser PDF.
    - Cada campo deve conter um arquivo da classe esperada.
    - Nao pode haver dois arquivos da mesma classe documental.
    - 'autos' e obrigatorio.
    - UF e valor da causa sao extraidos dos autos.
    """
    binarios = {doc: 0 for doc in TODOS_DOCUMENTOS}
    docs_presentes: list[str] = []
    classificacao_arquivos: list[dict[str, str]] = []
    classe_para_arquivos: dict[str, list[str]] = {}

    uploads = _carregar_arquivos_recebidos(arquivos)
    if not uploads:
        raise ValueError("Nenhum arquivo foi enviado. Anexe ao menos o documento de Autos.")

    pasta_tmp = Path(tempfile.mkdtemp(prefix="jurisia_upload_"))
    autos_texto: str | None = None

    try:
        for campo, arquivo in uploads:
            if not arquivo.filename.lower().endswith(".pdf"):
                raise ValueError(f"O arquivo '{arquivo.filename}' deve estar em PDF.")

            caminho_tmp = _salvar_upload_temporario(arquivo, pasta_tmp)
            try:
                texto = read_pdf_text(caminho_tmp)
            except Exception as exc:
                raise ValueError(
                    f"Falha ao ler o PDF '{arquivo.filename}'. "
                    "Verifique se o arquivo esta integro e tente novamente."
                ) from exc
            if not texto.strip():
                raise ValueError(
                    f"O arquivo '{arquivo.filename}' nao possui texto extraivel. "
                    "Tente um PDF com OCR ou melhor qualidade."
                )
            classe_detectada = classify_document(arquivo.filename, texto)

            classe_esperada = CAMPO_PARA_CLASSE_EXTRATOR[campo]
            if classe_detectada == "unknown":
                raise ValueError(
                    f"Nao foi possivel classificar o arquivo '{arquivo.filename}'. "
                    "Revise o conteudo e tente novamente."
                )

            if classe_detectada != classe_esperada:
                raise ValueError(
                    f"Classe invalida para '{campo}': arquivo '{arquivo.filename}' foi "
                    f"identificado como '{ROTULO_CLASSE.get(classe_detectada, classe_detectada)}'."
                )

            classe_para_arquivos.setdefault(classe_detectada, []).append(arquivo.filename)
            interno = CLASSE_EXTRATOR_PARA_INTERNO[classe_detectada]
            binarios[interno] = 1
            docs_presentes.append(interno)
            classificacao_arquivos.append(
                {
                    "arquivo": arquivo.filename,
                    "campo_enviado": campo,
                    "classe_detectada": classe_detectada,
                    "classe_esperada": classe_esperada,
                }
            )

            if classe_detectada == "autos":
                autos_texto = texto

        duplicados = [
            ROTULO_CLASSE.get(classe, classe)
            for classe, arquivos_mesma_classe in classe_para_arquivos.items()
            if len(arquivos_mesma_classe) > 1
        ]
        if duplicados:
            raise ValueError(
                "Foram enviados documentos duplicados para a(s) classe(s): "
                + ", ".join(duplicados)
                + "."
            )

        if binarios.get("autos", 0) == 0:
            raise ValueError(
                "Documento 'Autos' e obrigatorio e nao foi encontrado. "
                "Por favor, anexe os Autos do processo."
            )

        if not autos_texto:
            raise ValueError("Nao foi possivel ler o texto do documento de Autos.")

        numero_processo = extract_numero_processo(autos_texto)
        uf = extract_uf(autos_texto)
        valor_causa = extract_valor_causa(autos_texto)

        faltas_extracao = []
        if not uf:
            faltas_extracao.append("UF")
        if valor_causa is None:
            faltas_extracao.append("Valor da causa")

        if faltas_extracao:
            raise ValueError(
                "Nao foi possivel extrair "
                + " e ".join(faltas_extracao)
                + " a partir dos Autos. Verifique a qualidade do PDF."
            )

        docs_faltantes = [doc for doc, presente in binarios.items() if presente == 0]

        logger.info(
            "Documentos validados com extrator: presentes=%s | faltantes=%s | uf=%s | valor_causa=%.2f",
            docs_presentes,
            docs_faltantes,
            uf,
            valor_causa,
        )

        return {
            "binarios": binarios,
            "docs_presentes": docs_presentes,
            "docs_faltantes": docs_faltantes,
            "classificacao_arquivos": classificacao_arquivos,
            "extraidos_autos": {
                "numero_processo": numero_processo,
                "uf": uf,
                "valor_causa": valor_causa,
            },
            "valido": True,
        }
    finally:
        shutil.rmtree(pasta_tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# MÓDULO 2 — Modelos Estatísticos (Placeholders)
# ---------------------------------------------------------------------------


INFERENCE_OUTPUT_KEYS = (
    "P(E | ¬A, X)",
    "E[α | UF]",
    "E[VP| A,VT]",
    "[VP| A,VT]_lower",
    "[VP| A,VT]_upper",
)


def _clamp(value: float, minimo: float, maximo: float) -> float:
    return max(minimo, min(maximo, value))


def montar_case_dict(uf: str, valor_causa: float, docs_binarios: dict[str, int]) -> dict[str, Any]:
    return {
        "UF": uf.upper(),
        "Contrato": int(docs_binarios.get("contrato", 0)),
        "Extrato": int(docs_binarios.get("extrato", 0)),
        "Comprovante de crédito": int(docs_binarios.get("comprovante", 0)),
        "Dossiê": int(docs_binarios.get("dossie", 0)),
        "Demonstrativo de evolução da dívida": int(docs_binarios.get("demonstrativo", 0)),
        "Laudo referenciado": int(docs_binarios.get("laudo", 0)),
        "Valor da causa": float(valor_causa),
    }


def _buscar_chave(raw: dict[str, Any], chaves: tuple[str, ...]) -> Any:
    for chave in chaves:
        if chave in raw:
            return raw[chave]
    raise KeyError(chaves[0])


def _normalizar_saida_modelo(raw: dict[str, Any], valor_causa: float) -> dict[str, float]:
    p_e = float(
        _buscar_chave(
            raw,
            (
                "P(E | ¬A, X)",
                "P(E | ~A, X)",
                "P(E|¬A,X)",
                "P(E|~A,X)",
            ),
        )
    )
    alpha_pred = float(
        _buscar_chave(
            raw,
            (
                "E[α | UF]",
                "E[alpha | UF]",
                "E[beta | UF]",
            ),
        )
    )
    valor_pred = float(
        _buscar_chave(
            raw,
            (
                "E[VP| A,VT]",
                "E[VP|A,VT]",
                "E[VP | A, VT]",
                "E[VP | A,VT]",
                "E[VP| A, VT]",
                "E[VP|A, VT]",
            ),
        )
    )
    valor_lower = float(
        _buscar_chave(
            raw,
            (
                "[VP| A,VT]_lower",
                "[VP|A,VT]_lower",
                "[VP | A, VT]_lower",
                "[VP | A,VT]_lower",
                "[VP| A, VT]_lower",
                "[VP|A, VT]_lower",
            ),
        )
    )
    valor_upper = float(
        _buscar_chave(
            raw,
            (
                "[VP| A,VT]_upper",
                "[VP|A,VT]_upper",
                "[VP | A, VT]_upper",
                "[VP | A,VT]_upper",
                "[VP| A, VT]_upper",
                "[VP|A, VT]_upper",
            ),
        )
    )

    p_e = _clamp(p_e, 0.0, 1.0)
    alpha_pred = _clamp(alpha_pred, 0.0, 1.0)
    valor_pred = max(0.0, valor_pred)
    valor_lower = max(0.0, valor_lower)
    valor_upper = max(0.0, valor_upper)

    if valor_lower > valor_upper:
        valor_lower, valor_upper = valor_upper, valor_lower

    valor_upper = max(valor_upper, valor_pred)
    valor_lower = min(valor_lower, valor_pred)

    # Limite superior generoso para evitar outliers absurdos no PoC.
    limite_superior = max(valor_causa * 2.0, valor_causa + 1.0)
    valor_pred = _clamp(valor_pred, 0.0, limite_superior)
    valor_lower = _clamp(valor_lower, 0.0, limite_superior)
    valor_upper = _clamp(valor_upper, 0.0, limite_superior)

    return {
        "P(E | ¬A, X)": round(p_e, 6),
        "E[α | UF]": round(alpha_pred, 6),
        "E[VP| A,VT]": round(valor_pred, 2),
        "[VP| A,VT]_lower": round(valor_lower, 2),
        "[VP| A,VT]_upper": round(valor_upper, 2),
    }


def _dummy_inference(case_dict: dict[str, Any]) -> dict[str, float]:
    """
    Fallback dummy usado apenas quando inference.py não está disponível.
    """
    uf = str(case_dict.get("UF", "DEFAULT")).upper()
    valor_causa = float(case_dict.get("Valor da causa", 0.0) or 0.0)

    docs_keys = [
        "Contrato",
        "Extrato",
        "Comprovante de crédito",
        "Dossiê",
        "Demonstrativo de evolução da dívida",
        "Laudo referenciado",
    ]
    docs_presentes = sum(int(case_dict.get(chave, 0)) for chave in docs_keys)
    total_docs = len(docs_keys)
    doc_score = docs_presentes / total_docs if total_docs else 0.0

    uf_risco = {
        "SP": 0.02,
        "RJ": 0.06,
        "MG": 0.01,
        "RS": 0.00,
        "PR": 0.01,
        "DEFAULT": 0.04,
    }
    risco_uf = uf_risco.get(uf, uf_risco["DEFAULT"])

    p_e = 0.22 + (0.58 * doc_score) - risco_uf
    p_e = _clamp(p_e, 0.05, 0.95)

    alpha_pred = 0.78 - (0.34 * doc_score) + (0.25 * risco_uf)
    alpha_pred = _clamp(alpha_pred, 0.15, 0.95)

    # E[VP|A,VT] modelado como fração linear heterocedástica do VT.
    frac_acordo = 0.62 - (0.24 * doc_score) + (0.20 * risco_uf)
    frac_acordo = _clamp(frac_acordo, 0.12, 0.90)
    valor_pred = valor_causa * frac_acordo

    spread = 0.08 + ((1 - doc_score) * 0.10) + (min(valor_causa, 500_000) / 500_000) * 0.05
    valor_lower = valor_pred * (1 - spread)
    valor_upper = valor_pred * (1 + spread)

    return _normalizar_saida_modelo(
        {
            "P(E | ¬A, X)": p_e,
            "E[α | UF]": alpha_pred,
            "E[VP| A,VT]": valor_pred,
            "[VP| A,VT]_lower": valor_lower,
            "[VP| A,VT]_upper": valor_upper,
        },
        valor_causa=valor_causa,
    )


def _carregar_executor_inference() -> tuple[Any | None, str | None]:
    modulos_candidatos = (
        "src.policy.app.inference",
        "policy.app.inference",
        "inference",
    )
    candidatos = ("predict_case", "infer_case", "run_inference", "predict", "inference")

    for modulo in modulos_candidatos:
        try:
            inference_module = importlib.import_module(modulo)
        except Exception:
            continue

        for nome in candidatos:
            fn = getattr(inference_module, nome, None)
            if callable(fn):
                return fn, f"{modulo}.{nome}"
    return None, None


INFERENCE_EXECUTOR, INFERENCE_EXECUTOR_NAME = _carregar_executor_inference()


def executar_modelos(case_dict: dict[str, Any]) -> tuple[dict[str, float], str]:
    valor_causa = float(case_dict.get("Valor da causa", 0.0) or 0.0)

    if INFERENCE_EXECUTOR is None:
        return _dummy_inference(case_dict), "dummy_sem_inference.py"

    try:
        raw = INFERENCE_EXECUTOR(case_dict)
        if not isinstance(raw, dict):
            raise TypeError("inference.py retornou tipo inválido; esperado dict.")
        saida = _normalizar_saida_modelo(raw, valor_causa=valor_causa)
        return saida, f"inference.py::{INFERENCE_EXECUTOR_NAME}"
    except Exception as exc:
        logger.warning("Falha ao executar inference.py (%s). Usando dummy de fallback.", exc)
        return _dummy_inference(case_dict), "dummy_fallback_erro_inference.py"


def calcular_valor_esperado_defesa_sem_acordo(valor_causa: float, p_exito: float, alpha_pred: float) -> float:
    """
    E(VP|~A) = P(~E) * E(alpha|UF) * VT
    Onde alpha equivale ao beta descrito na regra de negócio.
    """
    valor = (1 - p_exito) * alpha_pred * valor_causa
    return round(max(0.0, valor), 2)


def calcular_valor_sugerido_acordo(
    valor_causa: float,
    valor_esperado_acordo: float,
    p_exito: float,
    intervalo_lower: float | None = None,
    intervalo_upper: float | None = None,
) -> float:
    """
    Placeholder de sugestão comercial:
    ancora no valor esperado com viés para a banda inferior e ajuste por risco.
    """
    base = valor_esperado_acordo
    if intervalo_lower is not None:
        base = (0.7 * valor_esperado_acordo) + (0.3 * intervalo_lower)

    ajuste_risco = (0.5 - p_exito) * 0.08 * valor_causa
    sugerido = base + ajuste_risco

    piso = valor_causa * 0.12
    teto = valor_causa * 0.90
    if intervalo_upper is not None:
        teto = min(teto, intervalo_upper)
    sugerido = max(piso, min(teto, sugerido))
    return round(sugerido, 2)


# ---------------------------------------------------------------------------
# MÓDULO 3 — Integração com LLM (Placeholder OpenAI)
# ---------------------------------------------------------------------------


def gerar_justificativa_openai(
    recomendacao: str,
    valores_esperados: dict[str, float],
    docs_faltantes: list[str],
    p_exito: float,
    case_dict: dict[str, Any],
    saida_modelo: dict[str, float],
    alpha_pred: float,
    valor_defesa: float,
    fonte_modelo: str,
) -> str:
    def _fallback_justificativa() -> str:
        delta = abs(valores_esperados["acordo"] - valores_esperados["defesa"])
        docs_str = ", ".join(d.capitalize() for d in docs_faltantes) if docs_faltantes else "nenhum"
        return (
            f"**Analise Estrategica — Recomendacao: {recomendacao}**\n\n"
            f"Comparacao de custo esperado: E(VP|A)=R$ {valores_esperados['acordo']:,.2f} "
            f"vs E(VP|~A)=R$ {valores_esperados['defesa']:,.2f}. "
            f"Diferenca absoluta: R$ {delta:,.2f}.\n\n"
            f"P(E | ¬A, X)={p_exito:.2%}, E(α|UF)={alpha_pred:.2%} (α equivale ao β da explicacao do modelo). "
            f"O valor esperado do acordo foi estimado em R$ {saida_modelo['E[VP| A,VT]']:,.2f}, "
            f"com faixa [{saida_modelo['[VP| A,VT]_lower']:,.2f}, {saida_modelo['[VP| A,VT]_upper']:,.2f}].\n\n"
            f"Documentos faltantes: {docs_str}. Fonte dos preditores: {fonte_modelo}."
        )

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return _fallback_justificativa()

    try:
        from openai import OpenAI
    except Exception:
        return _fallback_justificativa()

    model = os.environ.get("OPENAI_DECISION_MODEL", "gpt-4o-mini")
    client = OpenAI(api_key=api_key)

    system_prompt = (
        "Voce e um analista juridico-quantitativo sênior. Explique em portugues clara para advogado "
        "por que o modelo recomendou ACORDO ou DEFESA. Considere explicitamente: "
        "P(E | ¬A, X), E[α | UF] (onde α equivale ao β da explicacao), E[VP|A,VT], intervalo de incerteza "
        "e E(VP|~A)=P(~E)*E(α|UF)*VT. Estruture em 4 blocos curtos: sinais do caso, probabilidades, "
        "comparacao de expectativas e recomendacao final com riscos. Responda em Markdown."
    )

    user_prompt = (
        "Dados do caso (entrada do modelo):\n"
        + json.dumps(case_dict, ensure_ascii=False, indent=2)
        + "\n\nSaida dos modelos:\n"
        + json.dumps(saida_modelo, ensure_ascii=False, indent=2)
        + "\n\nResumo de decisao:\n"
        + json.dumps(
            {
                "recomendacao": recomendacao,
                "E(VP|A)": valores_esperados["acordo"],
                "E(VP|~A)": valor_defesa,
                "sugestao_acordo": valores_esperados.get("sugestao_acordo"),
                "docs_faltantes": docs_faltantes,
                "fonte_modelo": fonte_modelo,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=900,
        )
        texto = (response.choices[0].message.content or "").strip()
        return texto or _fallback_justificativa()
    except Exception as exc:
        logger.warning("Falha ao gerar justificativa via OpenAI (%s). Usando fallback local.", exc)
        return _fallback_justificativa()


# ---------------------------------------------------------------------------
# MÓDULO 4 — Rotas Flask
# ---------------------------------------------------------------------------


@app.route("/", methods=["GET"])
def index():
    return render_template("analise.html")


@app.route("/lancamentos", methods=["GET"])
def lancamentos_page():
    return render_template("painel_lancamentos.html")


@app.route("/api/lancamentos", methods=["GET"])
def listar_lancamentos():
    limit = request.args.get("limit", default=80, type=int)
    limit = max(1, min(limit, 500))

    conn = conectar_db()

    total = conn.execute("SELECT COUNT(*) AS total FROM analises").fetchone()["total"]
    completos = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM analises
        WHERE numero_processo IS NOT NULL
          AND uf IS NOT NULL
          AND valor_causa IS NOT NULL
        """
    ).fetchone()["n"]

    rec_dist = conn.execute(
        "SELECT recomendacao_ia, COUNT(*) AS n FROM analises GROUP BY recomendacao_ia"
    ).fetchall()
    feedback_preenchido = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM analises_feedback
        WHERE advogado_seguiu IS NOT NULL
           OR desfecho_real IS NOT NULL
           OR valor_pago IS NOT NULL
        """
    ).fetchone()["n"]

    top_ufs = conn.execute(
        "SELECT uf, COUNT(*) AS n FROM analises WHERE uf IS NOT NULL GROUP BY uf ORDER BY n DESC LIMIT 5"
    ).fetchall()

    rows = conn.execute(
        """
        SELECT
            a.id,
            a.criado_em,
            a.numero_processo,
            a.uf,
            a.valor_causa,
            a.recomendacao_ia,
            a.e_vp_acordo,
            a.e_vp_defesa,
            a.valor_sugerido_acordo,
            a.p_exito,
            a.docs_presentes,
            a.docs_faltantes,
            f.id AS feedback_id,
            f.criado_em AS feedback_criado_em,
            f.advogado_seguiu,
            f.desfecho_real,
            f.valor_pago,
            f.modelo_acertou,
            f.observacoes,
            f.atualizado_em
        FROM analises a
        LEFT JOIN analises_feedback f ON f.analise_id = a.id
        ORDER BY a.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    conn.close()

    lancamentos = []
    for row in rows:
        try:
            docs_presentes = json.loads(row["docs_presentes"])
        except Exception:
            docs_presentes = []
        try:
            docs_faltantes = json.loads(row["docs_faltantes"])
        except Exception:
            docs_faltantes = []

        lancamentos.append(
            {
                "id": row["id"],
                "criado_em": row["criado_em"],
                "numero_processo": row["numero_processo"],
                "uf": row["uf"],
                "valor_causa": row["valor_causa"],
                "recomendacao": row["recomendacao_ia"],
                "e_vp_acordo": row["e_vp_acordo"],
                "e_vp_defesa": row["e_vp_defesa"],
                "valor_sugerido_acordo": row["valor_sugerido_acordo"],
                "p_exito": row["p_exito"],
                "docs_presentes": docs_presentes,
                "docs_faltantes": docs_faltantes,
                "feedback": {
                    "id": row["feedback_id"],
                    "criado_em": row["feedback_criado_em"],
                    "advogado_seguiu": row["advogado_seguiu"],
                    "desfecho_real": row["desfecho_real"],
                    "valor_pago": row["valor_pago"],
                    "modelo_acertou": row["modelo_acertou"],
                    "observacoes": row["observacoes"],
                    "atualizado_em": row["atualizado_em"],
                },
            }
        )

    return jsonify(
        {
            "resumo": {
                "total_lancamentos": total,
                "taxa_extracao_completa": round((completos / total) * 100, 2) if total else 0,
                "feedback_preenchido": feedback_preenchido,
                "distribuicao_recomendacao": {r["recomendacao_ia"]: r["n"] for r in rec_dist},
                "top_ufs": [{"uf": r["uf"], "n": r["n"]} for r in top_ufs],
            },
            "lancamentos": lancamentos,
        }
    )


@app.route("/api/lancamentos/<int:analise_id>", methods=["PATCH"])
def atualizar_lancamento(analise_id: int):
    payload = request.get_json(silent=True) or {}
    try:
        resultado = atualizar_dados_analise(analise_id=analise_id, payload=payload)
        return jsonify({"ok": True, "resultado": resultado}), 200
    except ValueError as exc:
        mensagem = str(exc)
        if "nao encontrada" in mensagem.lower():
            return jsonify({"erro": mensagem}), 404
        return jsonify({"erro": mensagem}), 400
    except Exception as exc:
        logger.error("Erro ao atualizar analise %s: %s", analise_id, exc, exc_info=True)
        return jsonify({"erro": "Erro interno ao atualizar analise."}), 500


@app.route("/api/feedback", methods=["POST"])
def salvar_feedback():
    payload = request.get_json(silent=True) or {}

    analise_id_raw = payload.get("analise_id")
    try:
        analise_id = int(analise_id_raw)
        if analise_id <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"erro": "Campo 'analise_id' deve ser inteiro."}), 400

    advogado_seguiu_raw = payload.get("advogado_seguiu")
    if advogado_seguiu_raw is None:
        advogado_seguiu = None
    elif isinstance(advogado_seguiu_raw, bool):
        advogado_seguiu = int(advogado_seguiu_raw)
    elif advogado_seguiu_raw in (0, 1):
        advogado_seguiu = int(advogado_seguiu_raw)
    else:
        return jsonify({"erro": "Campo 'advogado_seguiu' deve ser boolean, 0, 1 ou null."}), 400

    desfecho_real = payload.get("desfecho_real")
    if desfecho_real is not None:
        desfecho_real = str(desfecho_real).strip().upper()
        if desfecho_real not in {"ACORDO", "DEFESA"}:
            return jsonify({"erro": "Campo 'desfecho_real' deve ser 'ACORDO', 'DEFESA' ou null."}), 400

    if payload.get("status_negociacao") is not None:
        return jsonify({"erro": "Campo 'status_negociacao' foi descontinuado. Informe apenas o desfecho final."}), 400
    if payload.get("valor_final_acordo") is not None:
        return jsonify({"erro": "Campo 'valor_final_acordo' foi descontinuado. Use 'valor_pago'."}), 400
    if payload.get("valor_real") is not None:
        return jsonify({"erro": "Campo 'valor_real' foi descontinuado. Use 'valor_pago'."}), 400

    valor_pago = payload.get("valor_pago")
    if valor_pago is not None:
        try:
            valor_pago = float(valor_pago)
            if not math.isfinite(valor_pago):
                raise ValueError
            if valor_pago < 0:
                raise ValueError
        except (ValueError, TypeError):
            return jsonify({"erro": "Campo 'valor_pago' deve ser numero >= 0 ou null."}), 400

    if valor_pago is not None and desfecho_real is None:
        return jsonify({"erro": "Informe 'desfecho_real' junto com 'valor_pago' para registrar o resultado final."}), 400

    observacoes = payload.get("observacoes")
    if observacoes is not None:
        observacoes = str(observacoes).strip()[:2000]

    try:
        resultado = registrar_feedback_analise(
            analise_id=analise_id,
            advogado_seguiu=advogado_seguiu,
            desfecho_real=desfecho_real,
            valor_pago=valor_pago,
            observacoes=observacoes,
        )
        return jsonify({"ok": True, "resultado": resultado}), 200
    except ValueError as exc:
        return jsonify({"erro": str(exc)}), 404
    except Exception as exc:
        logger.error("Erro ao salvar feedback da analise %s: %s", analise_id, exc, exc_info=True)
        return jsonify({"erro": "Erro interno ao salvar feedback."}), 500


@app.route("/api/eficacia", methods=["GET"])
def obter_eficacia():
    conn = conectar_db()
    metricas = calcular_metricas_gerenciais(conn)
    conn.close()

    return jsonify(
        {
            "total_analises": metricas["total_analises"],
            "com_feedback": metricas["com_feedback"],
            "avaliadas": metricas["com_desfecho"],
            "taxa_aderencia": metricas["taxa_aderencia"],
            "acuracia_modelo": metricas["acuracia_recomendacao"],
            "pagamentos_registrados": metricas["pagamentos_registrados"],
            "valor_total_pago": metricas["valor_total_pago"],
            "valor_total_cenario_sem_modelo": metricas["valor_total_cenario_sem_modelo"],
            "economia_total_modelo": metricas["economia_total_modelo"],
            "economia_media_modelo": metricas["economia_media_modelo"],
            "economia_percentual_modelo": metricas["economia_percentual_modelo"],
            "taxa_casos_economia_positiva": metricas["taxa_casos_economia_positiva"],
        }
    )


@app.route("/api/relatorio-ia", methods=["POST"])
def gerar_relatorio_ia():
    try:
        conn = conectar_db()
        metricas = calcular_metricas_gerenciais(conn)
        conn.close()

        relatorio, model = gerar_relatorio_openai(metricas)

        return jsonify(
            {
                "ok": True,
                "model": model,
                "gerado_em": datetime.utcnow().isoformat() + "Z",
                "metricas": metricas,
                "relatorio_ia": relatorio,
            }
        ), 200
    except RuntimeError as exc:
        return jsonify({"erro": str(exc)}), 400
    except Exception as exc:
        logger.error("Falha ao gerar relatorio gerencial via OpenAI: %s", exc, exc_info=True)
        return jsonify({"erro": "Erro interno ao gerar relatorio com IA."}), 500


@app.route("/api/confirmar-analise", methods=["POST"])
def confirmar_analise():
    payload = request.get_json(silent=True) or {}
    pendente_token = str(payload.get("pendente_token", "")).strip()
    if not pendente_token:
        return jsonify({"erro": "Campo 'pendente_token' e obrigatorio."}), 400

    conn = conectar_db()
    limpar_analises_pendentes_db(conn)
    pendente = conn.execute(
        "SELECT payload_analise FROM analises_pendentes WHERE token = ?",
        (pendente_token,),
    ).fetchone()
    if not pendente:
        conn.close()
        return jsonify({"erro": "Analise pendente nao encontrada ou expirada. Gere novamente a analise."}), 404

    try:
        dados = json.loads(pendente["payload_analise"])
    except Exception:
        conn.close()
        return jsonify({"erro": "Dados pendentes invalidos. Gere novamente a analise."}), 500

    try:
        analise_id = registrar_analise(
            numero_processo=dados.get("numero_processo"),
            uf=dados.get("uf"),
            valor_causa=float(dados.get("valor_causa")),
            recomendacao=str(dados.get("recomendacao")),
            valor_acordo=float(dados.get("valor_acordo")),
            valor_defesa=float(dados.get("valor_defesa")),
            valor_sugerido_acordo=(
                float(dados["valor_sugerido_acordo"])
                if dados.get("valor_sugerido_acordo") is not None
                else None
            ),
            p_exito=float(dados.get("p_exito")),
            docs_presentes=list(dados.get("docs_presentes", [])),
            docs_faltantes=list(dados.get("docs_faltantes", [])),
            docs_binarios=dict(dados.get("docs_binarios", {})),
        )
        conn.execute("DELETE FROM analises_pendentes WHERE token = ?", (pendente_token,))
        conn.commit()
        conn.close()
    except Exception as exc:
        conn.close()
        logger.error("Erro ao confirmar analise pendente token=%s: %s", pendente_token, exc, exc_info=True)
        return jsonify({"erro": "Erro interno ao confirmar e salvar a analise."}), 500

    return jsonify(
        {
            "ok": True,
            "resultado": {
                "analise_id": analise_id,
                "salvo_em": utc_now_iso(),
            },
        }
    ), 200


@app.route("/analisar", methods=["POST"])
def analisar():
    try:
        resultado_docs = validar_documentos(request.files)

        docs_binarios = resultado_docs["binarios"]
        docs_presentes = resultado_docs["docs_presentes"]
        docs_faltantes = [d for d in resultado_docs["docs_faltantes"] if d != "autos"]

        extraidos = resultado_docs["extraidos_autos"]
        valor_causa = float(extraidos["valor_causa"])
        uf = str(extraidos["uf"]).upper()
        numero_processo = extraidos.get("numero_processo")

        case_dict = montar_case_dict(uf=uf, valor_causa=valor_causa, docs_binarios=docs_binarios)
        saida_modelo, fonte_modelo = executar_modelos(case_dict)

        p_exito = float(saida_modelo["P(E | ¬A, X)"])
        alpha_pred = float(saida_modelo["E[α | UF]"])
        valor_acordo = float(saida_modelo["E[VP| A,VT]"])
        valor_acordo_lower = float(saida_modelo["[VP| A,VT]_lower"])
        valor_acordo_upper = float(saida_modelo["[VP| A,VT]_upper"])
        valor_defesa = calcular_valor_esperado_defesa_sem_acordo(
            valor_causa=valor_causa,
            p_exito=p_exito,
            alpha_pred=alpha_pred,
        )

        if valor_acordo < valor_defesa:
            recomendacao = "ACORDO"
        else:
            recomendacao = "DEFESA"

        valor_sugerido_acordo = None
        if recomendacao == "ACORDO":
            valor_sugerido_acordo = calcular_valor_sugerido_acordo(
                valor_causa=valor_causa,
                valor_esperado_acordo=valor_acordo,
                p_exito=p_exito,
                intervalo_lower=valor_acordo_lower,
                intervalo_upper=valor_acordo_upper,
            )

        valores_esperados = {
            "acordo": valor_acordo,
            "defesa": valor_defesa,
            "sugestao_acordo": valor_sugerido_acordo,
            "acordo_intervalo": {
                "lower": valor_acordo_lower,
                "upper": valor_acordo_upper,
            },
            "alpha_equiv_beta": alpha_pred,
        }

        justificativa = gerar_justificativa_openai(
            recomendacao=recomendacao,
            valores_esperados=valores_esperados,
            docs_faltantes=docs_faltantes,
            p_exito=p_exito,
            case_dict=case_dict,
            saida_modelo=saida_modelo,
            alpha_pred=alpha_pred,
            valor_defesa=valor_defesa,
            fonte_modelo=fonte_modelo,
        )

        pendente_token = criar_analise_pendente(
            {
                "numero_processo": numero_processo,
                "uf": uf,
                "valor_causa": valor_causa,
                "case_dict": case_dict,
                "recomendacao": recomendacao,
                "valor_acordo": valor_acordo,
                "valor_defesa": valor_defesa,
                "valor_sugerido_acordo": valor_sugerido_acordo,
                "p_exito": p_exito,
                "alpha_pred": alpha_pred,
                "docs_presentes": docs_presentes,
                "docs_faltantes": docs_faltantes,
                "docs_binarios": docs_binarios,
            }
        )

        resposta = {
            "recomendacao": recomendacao,
            "probabilidade_exito": p_exito,
            "valores_esperados": valores_esperados,
            "predicoes_modelo": {
                "entrada": case_dict,
                "saida": saida_modelo,
                "fonte": fonte_modelo,
            },
            "documentos": {
                "presentes": docs_presentes,
                "faltantes": docs_faltantes,
                "binarios": docs_binarios,
                "classificacao_arquivos": resultado_docs["classificacao_arquivos"],
            },
            "justificativa_ia": justificativa,
            "metadata": {
                "analise_id": None,
                "pendente_token": pendente_token,
                "salvo_no_banco": False,
                "numero_processo": numero_processo,
                "valor_causa": valor_causa,
                "uf": uf,
                "timestamp": utc_now_iso(),
                "fonte_dados": "extraido_dos_autos",
                "fonte_modelo": fonte_modelo,
            },
        }

        logger.info(
            "Analise concluida (pendente de confirmacao) | token=%s | fonte_modelo=%s | recomendacao=%s | processo=%s | uf=%s | valor_causa=%.2f",
            pendente_token,
            fonte_modelo,
            recomendacao,
            numero_processo,
            uf,
            valor_causa,
        )

        return jsonify(resposta), 200

    except ValueError as e:
        logger.warning("Erro de validacao: %s", str(e))
        return jsonify({"erro": str(e)}), 422

    except Exception as e:
        logger.error("Erro inesperado no processamento: %s", str(e), exc_info=True)
        return jsonify({"erro": "Erro interno no servidor. Tente novamente."}), 500


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "timestamp": datetime.utcnow().isoformat() + "Z"}), 200


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------


inicializar_banco()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    logger.info("Iniciando JurisIA na porta %d (debug=%s)", port, debug)
    app.run(host="0.0.0.0", port=port, debug=debug)
