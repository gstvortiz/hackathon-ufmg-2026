"""
JurisIA - Gerador de Relatorio Gerencial

Mede eficacia do modelo com base em duas tabelas:
- analises: previsoes do modelo
- analises_feedback: desfecho real, adesao do advogado e valor efetivamente pago
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from textwrap import dedent

DB_PATH_PADRAO = "juris_ia.db"

def _load_environment() -> None:
    try:
        from dotenv import load_dotenv
    except Exception:
        # Sem python-dotenv, o script segue usando variaveis de ambiente do sistema.
        return

    interface_dir = Path(__file__).resolve().parent
    project_root = interface_dir.parent.parent

    candidates = (
        project_root / ".env",
        project_root / ".env.example",
        project_root / ".env.ecample",
        interface_dir / ".env",
        interface_dir / ".env.example",
        interface_dir / ".env.ecample",
    )
    for env_path in candidates:
        if env_path.exists():
            load_dotenv(env_path, override=False)


_load_environment()

SCHEMA_ANALISES_SQL = """
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
    docs_binarios TEXT,
    -- legados (mantidos por compatibilidade):
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
# Banco de dados
# ---------------------------------------------------------------------------

def conectar(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(SCHEMA_ANALISES_SQL)
    conn.execute(SCHEMA_FEEDBACK_SQL)
    conn.commit()
    garantir_colunas(conn)
    sincronizar_feedback_pendente(conn)
    return conn


def garantir_colunas(conn: sqlite3.Connection) -> None:
    existentes_analises = {row["name"] for row in conn.execute("PRAGMA table_info(analises)").fetchall()}
    for col, col_type in COLUNAS_ESPERADAS_ANALISES.items():
        if col not in existentes_analises:
            conn.execute(f"ALTER TABLE analises ADD COLUMN {col} {col_type}")

    existentes_feedback = {row["name"] for row in conn.execute("PRAGMA table_info(analises_feedback)").fetchall()}
    for col, col_type in COLUNAS_ESPERADAS_FEEDBACK.items():
        if col not in existentes_feedback:
            conn.execute(f"ALTER TABLE analises_feedback ADD COLUMN {col} {col_type}")
    conn.commit()


def sincronizar_feedback_pendente(conn: sqlite3.Connection) -> None:
    agora = datetime.utcnow().isoformat() + "Z"
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


def gerar_numero_processo_fake() -> str:
    nnnnnnn = random.randint(1_000_000, 9_999_999)
    dd = random.randint(10, 99)
    aaaa = random.randint(2019, 2026)
    j = 8
    tr = random.randint(1, 27)
    oooo = random.randint(1000, 9999)
    return f"{nnnnnnn}-{dd}.{aaaa}.{j}.{tr:02d}.{oooo}"


def popular_dados_mock(conn: sqlite3.Connection, n: int = 120) -> None:
    count = conn.execute("SELECT COUNT(*) AS c FROM analises").fetchone()["c"]
    if count >= n:
        print(f"[INFO] Banco ja possui {count} registros. Pulando mock.")
        return

    random.seed(42)
    ufs = ["SP", "RJ", "MG", "RS", "PR", "BA", "CE", "GO", "PE", "SC"]
    docs_lista = ["autos", "contrato", "extrato", "comprovante", "dossie", "demonstrativo", "laudo"]

    base_date = datetime.now() - timedelta(days=90)

    for i in range(n):
        criado_em = (base_date + timedelta(days=i * 90 / n)).strftime("%Y-%m-%dT%H:%M:%SZ")
        uf = random.choice(ufs)
        valor_causa = round(random.uniform(10_000, 500_000), 2)
        p_exito = round(random.uniform(0.10, 0.90), 4)
        e_acordo = round(valor_causa * random.uniform(0.18, 0.48), 2)
        e_defesa = round(valor_causa * random.uniform(0.22, 0.62), 2)
        rec_ia = "ACORDO" if e_acordo < e_defesa else "DEFESA"
        valor_sugerido_acordo = round(e_acordo * random.uniform(0.92, 1.05), 2) if rec_ia == "ACORDO" else None
        numero_processo = gerar_numero_processo_fake()

        docs_ok = random.sample(docs_lista, k=random.randint(2, 7))
        docs_falta = [d for d in docs_lista if d not in docs_ok]
        docs_binarios = {d: int(d in docs_ok) for d in docs_lista}

        cursor = conn.execute(
            """
            INSERT INTO analises (
                criado_em, numero_processo, uf, valor_causa,
                recomendacao_ia, e_vp_acordo, e_vp_defesa, valor_sugerido_acordo, p_exito,
                docs_presentes, docs_faltantes, docs_binarios
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                criado_em,
                numero_processo,
                uf,
                valor_causa,
                rec_ia,
                e_acordo,
                e_defesa,
                valor_sugerido_acordo,
                p_exito,
                json.dumps(docs_ok, ensure_ascii=False),
                json.dumps(docs_falta, ensure_ascii=False),
                json.dumps(docs_binarios, ensure_ascii=False),
            ),
        )
        analise_id = int(cursor.lastrowid)

        if i < int(n * 0.78):
            advogado_seguiu = 1 if random.random() < 0.76 else 0
            desfecho_real = rec_ia if advogado_seguiu == 1 else ("DEFESA" if rec_ia == "ACORDO" else "ACORDO")

            if desfecho_real == "ACORDO":
                referencia = valor_sugerido_acordo if valor_sugerido_acordo is not None else e_acordo
                valor_pago = round(max(0.0, referencia * random.uniform(0.90, 1.18)), 2)
            else:
                valor_pago = round(max(0.0, e_defesa * random.uniform(0.85, 1.35)), 2)

            modelo_acertou = int(desfecho_real == rec_ia)
        else:
            advogado_seguiu = None
            desfecho_real = None
            valor_pago = None
            modelo_acertou = None

        conn.execute(
            """
            INSERT INTO analises_feedback (
                analise_id, criado_em, atualizado_em,
                advogado_seguiu, desfecho_real, valor_pago,
                modelo_acertou, observacoes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                analise_id,
                criado_em,
                criado_em,
                advogado_seguiu,
                desfecho_real,
                valor_pago,
                modelo_acertou,
                None,
            ),
        )

        # Espelha no legado para compatibilidade
        conn.execute(
            """
            UPDATE analises
            SET aderiu_recomend = ?, desfecho_real = ?, valor_real = ?
            WHERE id = ?
            """,
            (advogado_seguiu, desfecho_real, valor_pago, analise_id),
        )

    conn.commit()
    print(f"[INFO] {n} registros mock inseridos em analises + analises_feedback.")


# ---------------------------------------------------------------------------
# Metricas
# ---------------------------------------------------------------------------

def calcular_metricas(conn: sqlite3.Connection) -> dict:
    metricas: dict = {}

    total = conn.execute("SELECT COUNT(*) AS total FROM analises").fetchone()["total"]
    metricas["total_analises"] = total

    com_desfecho = conn.execute(
        "SELECT COUNT(*) AS c FROM analises_feedback WHERE desfecho_real IS NOT NULL"
    ).fetchone()["c"]
    metricas["com_desfecho"] = com_desfecho

    com_feedback = conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM analises_feedback
        WHERE advogado_seguiu IS NOT NULL
           OR desfecho_real IS NOT NULL
           OR valor_pago IS NOT NULL
        """
    ).fetchone()["c"]
    metricas["com_feedback"] = com_feedback

    taxa_aderencia = conn.execute(
        """
        SELECT AVG(CAST(advogado_seguiu AS REAL)) AS taxa
        FROM analises_feedback
        WHERE advogado_seguiu IS NOT NULL
        """
    ).fetchone()["taxa"]
    metricas["taxa_aderencia"] = round((taxa_aderencia or 0) * 100, 2)

    acc_row = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN a.recomendacao_ia = f.desfecho_real THEN 1 ELSE 0 END) AS acertos
        FROM analises a
        JOIN analises_feedback f ON f.analise_id = a.id
        WHERE f.desfecho_real IS NOT NULL
        """
    ).fetchone()

    if acc_row["total"]:
        metricas["acuracia_recomendacao"] = round((acc_row["acertos"] / acc_row["total"]) * 100, 2)
    else:
        metricas["acuracia_recomendacao"] = None

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
        for r in rows_fin:
            esperado = r["e_vp_acordo"] if r["recomendacao_ia"] == "ACORDO" else r["e_vp_defesa"]
            erros.append(abs(esperado - r["valor_observado"]))
        metricas["mae_financeiro"] = round(sum(erros) / len(erros), 2)
        metricas["rmse_financeiro"] = round(math.sqrt(sum(e * e for e in erros) / len(erros)), 2)
        metricas["n_mae"] = len(erros)
    else:
        metricas["mae_financeiro"] = None
        metricas["rmse_financeiro"] = None
        metricas["n_mae"] = 0

    dist_rec = conn.execute(
        "SELECT recomendacao_ia, COUNT(*) AS n FROM analises GROUP BY recomendacao_ia"
    ).fetchall()
    metricas["distribuicao_rec"] = {r["recomendacao_ia"]: r["n"] for r in dist_rec}

    dist_uf = conn.execute(
        "SELECT uf, COUNT(*) AS n FROM analises WHERE uf IS NOT NULL GROUP BY uf ORDER BY n DESC LIMIT 5"
    ).fetchall()
    metricas["distribuicao_uf_top5"] = {r["uf"]: r["n"] for r in dist_uf}

    row_medias = conn.execute(
        "SELECT AVG(valor_causa) AS vc, AVG(p_exito) AS pe FROM analises"
    ).fetchone()
    metricas["valor_causa_medio"] = round(row_medias["vc"] or 0, 2)
    metricas["p_exito_medio"] = round(row_medias["pe"] or 0, 4)

    periodo = conn.execute(
        "SELECT MIN(criado_em) AS ini, MAX(criado_em) AS fim FROM analises"
    ).fetchone()
    metricas["periodo"] = {"inicio": periodo["ini"], "fim": periodo["fim"]}

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

    for r in economia_rows:
        valor_pago = float(r["valor_pago"])
        valor_total_pago += valor_pago

        if r["recomendacao_ia"] == "ACORDO":
            esperado_recomendado = float(r["e_vp_acordo"])
            esperado_contrafactual = float(r["e_vp_defesa"])
        else:
            esperado_recomendado = float(r["e_vp_defesa"])
            esperado_contrafactual = float(r["e_vp_acordo"])

        valor_total_contrafactual += esperado_contrafactual
        economias_modelo.append(esperado_contrafactual - valor_pago)
        economias_vs_recomendado.append(esperado_recomendado - valor_pago)

    metricas["pagamentos_registrados"] = len(economias_modelo)
    metricas["valor_total_pago"] = round(valor_total_pago, 2) if economias_modelo else None
    metricas["valor_total_cenario_sem_modelo"] = round(valor_total_contrafactual, 2) if economias_modelo else None
    metricas["economia_total_modelo"] = round(sum(economias_modelo), 2) if economias_modelo else None
    metricas["economia_media_modelo"] = (
        round(sum(economias_modelo) / len(economias_modelo), 2) if economias_modelo else None
    )
    metricas["economia_mediana_modelo"] = (
        round(float(sorted(economias_modelo)[len(economias_modelo) // 2]), 2) if economias_modelo else None
    )
    metricas["economia_percentual_modelo"] = (
        round(((valor_total_contrafactual - valor_total_pago) / valor_total_contrafactual) * 100, 2)
        if valor_total_contrafactual > 0
        else None
    )
    metricas["casos_economia_positiva"] = sum(1 for e in economias_modelo if e > 0)
    metricas["taxa_casos_economia_positiva"] = (
        round((metricas["casos_economia_positiva"] / len(economias_modelo)) * 100, 2)
        if economias_modelo
        else None
    )
    metricas["economia_total_vs_previsto_recomendacao"] = (
        round(sum(economias_vs_recomendado), 2) if economias_vs_recomendado else None
    )
    metricas["economia_media_vs_previsto_recomendacao"] = (
        round(sum(economias_vs_recomendado) / len(economias_vs_recomendado), 2)
        if economias_vs_recomendado
        else None
    )

    verif = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN numero_processo IS NOT NULL AND numero_processo <> '' THEN 1 ELSE 0 END) AS ok_numero,
            SUM(CASE WHEN uf IS NOT NULL AND uf <> '' THEN 1 ELSE 0 END) AS ok_uf,
            SUM(CASE WHEN valor_causa IS NOT NULL AND valor_causa > 0 THEN 1 ELSE 0 END) AS ok_valor
        FROM analises
        """
    ).fetchone()

    total_verif = verif["total"] or 0

    amostra = conn.execute(
        """
        SELECT id, criado_em, numero_processo, uf, valor_causa
        FROM analises
        ORDER BY id DESC
        LIMIT 8
        """
    ).fetchall()

    metricas["verificacao_extracao"] = {
        "total_registros": total_verif,
        "numero_processo_extraido": int(verif["ok_numero"] or 0),
        "uf_extraida": int(verif["ok_uf"] or 0),
        "valor_causa_extraido": int(verif["ok_valor"] or 0),
        "taxa_numero_processo": round(((verif["ok_numero"] or 0) / total_verif) * 100, 2) if total_verif else 0,
        "taxa_uf": round(((verif["ok_uf"] or 0) / total_verif) * 100, 2) if total_verif else 0,
        "taxa_valor_causa": round(((verif["ok_valor"] or 0) / total_verif) * 100, 2) if total_verif else 0,
        "amostra_registros": [
            {
                "id": r["id"],
                "criado_em": r["criado_em"],
                "numero_processo": r["numero_processo"],
                "uf": r["uf"],
                "valor_causa": r["valor_causa"],
            }
            for r in amostra
        ],
    }

    return metricas


# ---------------------------------------------------------------------------
# Relatorio e LLM
# ---------------------------------------------------------------------------

def formatar_relatorio_texto(metricas: dict) -> str:
    brl = lambda v: f"R$ {v:,.2f}" if v is not None else "-"
    pct = lambda v: f"{v:.2f}%" if v is not None else "-"

    rec_acordo = metricas["distribuicao_rec"].get("ACORDO", 0)
    rec_defesa = metricas["distribuicao_rec"].get("DEFESA", 0)
    uf_str = " | ".join(f"{uf}: {n}" for uf, n in metricas["distribuicao_uf_top5"].items()) or "-"

    verif = metricas["verificacao_extracao"]
    amostra_txt = "\n".join(
        [
            f"  - ID {r['id']} | {r['numero_processo'] or '-'} | {r['uf'] or '-'} | {brl(r['valor_causa'])}"
            for r in verif["amostra_registros"]
        ]
    ) or "  - Sem dados"

    return dedent(
        f"""
        ============================================================
        JURISIA - RELATORIO GERENCIAL
        ============================================================
        Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}
        Periodo : {metricas['periodo']['inicio']} -> {metricas['periodo']['fim']}

        VOLUME
        - Total de analises: {metricas['total_analises']}
        - Com feedback preenchido: {metricas['com_feedback']}
        - Com desfecho real: {metricas['com_desfecho']}
        - Recom. ACORDO: {rec_acordo}
        - Recom. DEFESA: {rec_defesa}
        - Top UFs: {uf_str}

        PERFORMANCE
        - Taxa de aderencia: {pct(metricas['taxa_aderencia'])}
        - Acuracia da recomendacao: {pct(metricas['acuracia_recomendacao'])}
        - MAE financeiro (n={metricas['n_mae']}): {brl(metricas['mae_financeiro'])}
        - RMSE financeiro: {brl(metricas['rmse_financeiro'])}

        EFICIENCIA FINANCEIRA (COM MODELO)
        - Pagamentos registrados: {metricas['pagamentos_registrados']}
        - Valor total pago: {brl(metricas['valor_total_pago'])}
        - Valor total sem modelo (cenario contrafactual): {brl(metricas['valor_total_cenario_sem_modelo'])}
        - Economia total do modelo: {brl(metricas['economia_total_modelo'])}
        - Economia media por caso: {brl(metricas['economia_media_modelo'])}
        - Economia percentual do modelo: {pct(metricas['economia_percentual_modelo'])}
        - Casos com economia positiva: {metricas['casos_economia_positiva']} ({pct(metricas['taxa_casos_economia_positiva'])})

        ESTATISTICAS GERAIS
        - Valor medio da causa: {brl(metricas['valor_causa_medio'])}
        - P(exito) medio: {pct((metricas['p_exito_medio'] or 0) * 100)}

        VERIFICACAO DA EXTRACAO (AUTOS)
        - Numero do processo extraido: {verif['numero_processo_extraido']}/{verif['total_registros']} ({pct(verif['taxa_numero_processo'])})
        - UF extraida: {verif['uf_extraida']}/{verif['total_registros']} ({pct(verif['taxa_uf'])})
        - Valor da causa extraido: {verif['valor_causa_extraido']}/{verif['total_registros']} ({pct(verif['taxa_valor_causa'])})
        - Amostra para verificacao manual:
{amostra_txt}
        ============================================================
        """
    ).strip()


def gerar_analise_llm(metricas: dict, enviar: bool = False) -> str:
    system_prompt = dedent(
        """
        Voce e um analista senior de jurimetria. Recebera metricas do JurisIA
        e deve produzir uma analise executiva objetiva com:
        1) pontos fortes,
        2) riscos,
        3) 3 acoes priorizadas,
        4) observacoes sobre qualidade de extracao (numero do processo, UF, valor da causa),
        5) observacoes sobre eficacia preditiva com base no feedback real,
        6) leitura de economia do modelo comparando cenario sem modelo vs valor efetivamente pago.
        """
    ).strip()

    user_prompt = dedent(
        f"""
        Analise as metricas abaixo e produza uma sintese gerencial:

        {json.dumps(metricas, ensure_ascii=False, indent=2)}
        """
    ).strip()

    if not enviar:
        return dedent(
            f"""
            [MOCK - Chamada LLM nao realizada]

            SYSTEM PROMPT:
            {system_prompt}

            USER PROMPT:
            {user_prompt}
            """
        ).strip()

    try:
        import openai

        client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=700,
            temperature=0.2,
        )
        return response.choices[0].message.content
    except ImportError:
        return "[ERRO] Pacote openai nao instalado."
    except KeyError:
        return "[ERRO] OPENAI_API_KEY nao definida."
    except Exception as exc:
        return f"[ERRO] Falha na chamada OpenAI: {exc}"


def salvar_relatorio(texto: str, caminho: str) -> None:
    with open(caminho, "w", encoding="utf-8") as f:
        f.write(texto)
    print(f"[INFO] Relatorio salvo em: {caminho}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="JurisIA - Relatorio Gerencial")
    parser.add_argument("--db", default=DB_PATH_PADRAO, help="Caminho do SQLite")
    parser.add_argument("--output", default=None, help="Salvar relatorio em .txt")
    parser.add_argument("--enviar-llm", action="store_true", help="Enviar para OpenAI")
    parser.add_argument("--no-mock", action="store_true", help="Nao inserir dados mock")
    args = parser.parse_args()

    print("=" * 60)
    print("JurisIA - Relatorio Gerencial")
    print("=" * 60)
    print(f"Banco: {args.db}")
    print(f"Enviar LLM: {'Sim' if args.enviar_llm else 'Nao (mock)'}")

    conn = conectar(args.db)
    if not args.no_mock:
        popular_dados_mock(conn, n=120)

    metricas = calcular_metricas(conn)
    conn.close()

    relatorio = formatar_relatorio_texto(metricas)
    print("\n" + relatorio)

    analise_llm = gerar_analise_llm(metricas, enviar=args.enviar_llm)
    separador = "\n\n" + ("-" * 60) + "\nANALISE LLM\n" + ("-" * 60) + "\n"
    print(separador + analise_llm)

    if args.output:
        salvar_relatorio(relatorio + separador + analise_llm, args.output)


if __name__ == "__main__":
    main()
