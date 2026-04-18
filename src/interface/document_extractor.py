from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any, Literal

import pdfplumber

SubAssuntoStrategy = Literal["llm", "regex", "none"]


# --------------------------------------------------------------------------- #
# CNJ -> UF (justiça estadual, J=8). Mapeamento validado contra a base real.
# --------------------------------------------------------------------------- #
CNJ_UF_ESTADUAL: dict[str, str] = {
    "01": "AC", "02": "AL", "03": "AP", "04": "AM", "05": "BA",
    "06": "CE", "07": "DF", "08": "ES", "09": "GO", "10": "MA",
    "11": "MT", "12": "MS", "13": "MG", "14": "PA", "15": "PB",
    "16": "PR", "17": "PE", "18": "PI", "19": "RJ", "20": "RN",
    "21": "RS", "22": "RO", "23": "RR", "24": "SC", "25": "SE",
    "26": "SP", "27": "TO",
}

CNJ_REGEX = re.compile(
    r"\b(\d{7})[-\.]?(\d{2})[\.\-]?(\d{4})[\.\-]?(\d)[\.\-]?(\d{2})[\.\-]?(\d{4})\b"
)


def parse_cnj(text: str) -> str | None:
    m = CNJ_REGEX.search(text)
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}.{m.group(3)}.{m.group(4)}.{m.group(5)}.{m.group(6)}"


def uf_from_cnj(cnj: str) -> str | None:
    m = CNJ_REGEX.search(cnj or "")
    if not m or m.group(4) != "8":
        return None
    return CNJ_UF_ESTADUAL.get(m.group(5))


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _norm(s: str) -> str:
    return _strip_accents(s).lower()


def parse_brl(value: str) -> float | None:
    if not value:
        return None
    s = value.strip().replace("R$", "").replace(" ", "")
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# Classificação de tipo de documento
# --------------------------------------------------------------------------- #
DOC_TYPES = (
    "autos", "contrato", "extrato", "comprovante_credito",
    "dossie", "demonstrativo_divida", "laudo_referenciado",
)

# Padrões aplicados em texto normalizado (lowercase, sem acento).
# Ordem importa: 'autos' é checado primeiro porque a petição inicial cita
# os outros documentos no corpo, mas nenhum outro tipo contém frases
# típicas de petição.
CONTENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("autos",                re.compile(r"excelentissim[oa]\s+senhor|acao\s+declaratoria|pede\s+deferimento|da-se\s+(?:a|à)\s+causa|dos\s+pedidos")),
    ("demonstrativo_divida", re.compile(r"demonstrativo\s+de\s+evolucao\s+da\s+divida")),
    ("laudo_referenciado",   re.compile(r"laudo\s+referenciado")),
    ("comprovante_credito",  re.compile(r"comprovante\s+de\s+(operacao\s+de\s+)?credito|bacen")),
    ("dossie",               re.compile(r"dossie\s+de\s+verificacao|grafotecnica|liveness")),
    ("contrato",             re.compile(r"cedula\s+de\s+credito\s+bancario|clausulas\s+contratuais")),
    ("extrato",              re.compile(r"extrato\s+de\s+conta|saldo\s+anterior")),
]

FILENAME_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("autos",                re.compile(r"autos|peticao", re.I)),
    ("contrato",             re.compile(r"contrato|cedula", re.I)),
    ("extrato",              re.compile(r"extrato", re.I)),
    ("comprovante_credito",  re.compile(r"comprovante.*credito|bacen", re.I)),
    ("dossie",               re.compile(r"dossie", re.I)),
    ("demonstrativo_divida", re.compile(r"demonstrativo|evolucao.*divida", re.I)),
    ("laudo_referenciado",   re.compile(r"laudo", re.I)),
]


def classify_document(filename: str, text: str) -> str:
    norm_text = _norm(text)
    for doc_type, pat in CONTENT_PATTERNS:
        if pat.search(norm_text):
            return doc_type
    norm_name = _norm(filename)
    for doc_type, pat in FILENAME_PATTERNS:
        if pat.search(norm_name):
            return doc_type
    return "unknown"


# --------------------------------------------------------------------------- #
# Extração a partir dos Autos
# --------------------------------------------------------------------------- #
VALOR_CAUSA_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"d[áa]-se\s+(?:a|à)\s+causa\s+o?\s*valor\s+de\s*R?\$?\s*([\d\.,]+)", re.I),
    re.compile(r"valor\s+da\s+causa[:\s]+R?\$?\s*([\d\.,]+)", re.I),
    re.compile(r"valor\s+(?:atribu[ií]do\s+)?(?:à|a)\s+causa[:\s]+R?\$?\s*([\d\.,]+)", re.I),
]

GOLPE_KEYWORDS: list[str] = [
    "fraude", "fraudulent",
    "golpe", "golpista",
    "estelionat",
    "se passou por", "passou-se por",
    "engenharia social", "phishing",
    "link falso", "link suspeito",
    "falsari", "clonagem", "clonou",
    "falsa central", "falso atendente",
    "suposto funcionari", "suposta funcionari",
    "terceiro em nome", "terceiros em nome",
    "por terceiro em nome", "por terceiros em nome",
    "uso indevido de sua identidade", "uso indevido da identidade",
    "contratacao fraudulenta",
]


def extract_numero_processo(text: str) -> str | None:
    return parse_cnj(text)


def extract_uf(text: str) -> str | None:
    cnj = parse_cnj(text)
    if cnj and (uf := uf_from_cnj(cnj)):
        return uf
    m = re.search(r"Comarca\s+de\s+[\w\sà-ÿ]+?[/\-]([A-Z]{2})\b", text)
    return m.group(1) if m else None


def extract_valor_causa(text: str) -> float | None:
    for pat in VALOR_CAUSA_PATTERNS:
        m = pat.search(text)
        if m and (v := parse_brl(m.group(1))) is not None:
            return v
    return None


def classify_sub_assunto_regex(text: str) -> str:
    """Heurística local por keywords. Retorna 'Golpe' ou 'Genérico'."""
    norm = _norm(text)
    for kw in GOLPE_KEYWORDS:
        if _norm(kw) in norm:
            return "Golpe"
    return "Genérico"


# --------------------------------------------------------------------------- #
# Leitura de PDFs
# --------------------------------------------------------------------------- #
def read_pdf_text(path: Path | str) -> str:
    parts: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Schema do CSV de saída
# --------------------------------------------------------------------------- #
ASSUNTO_CONSTANTE = "Não reconhece operação"

CSV_COLUMNS = [
    "Número do processo", "UF", "Assunto", "Sub-assunto",
    "Resultado macro", "Resultado micro",
    "Valor da causa", "Valor da condenação/indenização",
    "Contrato", "Extrato", "Comprovante de crédito", "Dossiê",
    "Demonstrativo de evolução da dívida", "Laudo referenciado",
]

SUBSIDIO_TO_COLUMN = {
    "contrato": "Contrato",
    "extrato": "Extrato",
    "comprovante_credito": "Comprovante de crédito",
    "dossie": "Dossiê",
    "demonstrativo_divida": "Demonstrativo de evolução da dívida",
    "laudo_referenciado": "Laudo referenciado",
}


# --------------------------------------------------------------------------- #
# Pipeline principal
# --------------------------------------------------------------------------- #
def _resolve_sub_assunto(autos_text: str, strategy: SubAssuntoStrategy) -> tuple[str | None, str]:
    """Retorna (valor, fonte). Fonte ∈ {'llm', 'regex', 'skipped', 'llm->regex (...)'}."""
    if strategy == "none":
        return None, "skipped"
    if strategy == "regex":
        return classify_sub_assunto_regex(autos_text), "regex"
    if strategy == "llm":
        try:
            try:
                from .llm_subtopic import classify_sub_assunto_llm
            except ImportError:
                from llm_subtopic import classify_sub_assunto_llm
            return classify_sub_assunto_llm(autos_text), "llm"
        except Exception as e:
            return classify_sub_assunto_regex(autos_text), f"llm->regex ({type(e).__name__})"
    raise ValueError(f"Estratégia inválida: {strategy}")


def extract_from_folder(
    folder: str | Path,
    subassunto_strategy: SubAssuntoStrategy = "regex",
) -> dict[str, Any]:
    """Lê todos os PDFs da pasta e devolve {'row': {...}, 'meta': {...}}."""
    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError(f"Pasta inexistente: {folder}")

    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        raise ValueError(f"Nenhum PDF encontrado em {folder}")

    documents: dict[str, str] = {p.name: read_pdf_text(p) for p in pdfs}

    classified: dict[str, list[str]] = {t: [] for t in DOC_TYPES}
    unknown: list[str] = []
    for filename, text in documents.items():
        doc_type = classify_document(filename, text)
        (unknown if doc_type == "unknown" else classified[doc_type]).append(filename)

    autos_data = {"numero_processo": None, "uf": None, "valor_causa": None}
    sub_assunto: str | None = None
    sub_assunto_source = "skipped"
    if classified["autos"]:
        autos_text = documents[classified["autos"][0]]
        autos_data = {
            "numero_processo": extract_numero_processo(autos_text),
            "uf": extract_uf(autos_text),
            "valor_causa": extract_valor_causa(autos_text),
        }
        sub_assunto, sub_assunto_source = _resolve_sub_assunto(autos_text, subassunto_strategy)

    subsidios = {col: 0 for col in SUBSIDIO_TO_COLUMN.values()}
    for key, col in SUBSIDIO_TO_COLUMN.items():
        if classified[key]:
            subsidios[col] = 1

    row = {
        "Número do processo": autos_data["numero_processo"],
        "UF": autos_data["uf"],
        "Assunto": ASSUNTO_CONSTANTE,
        "Sub-assunto": sub_assunto,
        "Resultado macro": None,
        "Resultado micro": None,
        "Valor da causa": autos_data["valor_causa"],
        "Valor da condenação/indenização": None,
        **subsidios,
    }

    meta = {
        "source_folder": str(folder),
        "files_processed": list(documents.keys()),
        "classified_files": {k: v for k, v in classified.items() if v},
        "unknown_files": unknown,
        "sub_assunto_source": sub_assunto_source,
        "sentence_dependent_fields_null": [
            "Resultado macro", "Resultado micro", "Valor da condenação/indenização",
        ],
    }
    return {"row": row, "meta": meta}
