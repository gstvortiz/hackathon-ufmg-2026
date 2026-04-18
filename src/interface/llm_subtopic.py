"""
Sub-assunto classifier (Golpe | Generico) via OpenAI API.

This module is optional. If removed, document_extractor.py can fallback to regex.

API key lookup order:
1. OPENAI_API_KEY env var
2. .env na raiz do projeto
3. .env.example ou .env.ecample na raiz do projeto
4. .env, .env.example ou .env.ecample nesta pasta
"""
from __future__ import annotations

import os
import unicodedata
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

MODEL = "gpt-4o-mini"
MAX_INPUT_CHARS = 6000

SYSTEM_PROMPT = """Voce e um classificador especialista em peticoes iniciais de acoes civeis brasileiras onde o autor alega nao reconhecer a contratacao de um emprestimo contra uma instituicao financeira.

Classifique a peticao em UMA de duas categorias:

- "Golpe": o autor traz NARRATIVA ARTICULADA de fraude. Ele explica COMO a contratacao irregular teria ocorrido: terceiro que usou seus dados, fraude documental, uso indevido de identidade, estelionato, engenharia social, phishing, golpe telefonico, golpista que se passou por funcionario do banco, contratacao feita por terceiro em nome do autor, etc.

- "Generico": o autor apenas AFIRMA que nao reconhece a contratacao, SEM apresentar narrativa articulada de como o emprestimo foi contratado em seu nome. Sem historia de fraude ativa, sem terceiro identificado.

Responda APENAS com uma palavra: Golpe ou Generico. Nada mais."""


_client: OpenAI | None = None


def _load_local_dotenv() -> None:
    here = Path(__file__).resolve().parent
    project_root = here.parent.parent
    candidates = (
        project_root / ".env",
        project_root / ".env.example",
        project_root / ".env.ecample",
        here / ".env",
        here / ".env.example",
        here / ".env.ecample",
    )
    for env_path in candidates:
        if env_path.exists():
            load_dotenv(env_path, override=False)


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _load_local_dotenv()
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError(
                "OPENAI_API_KEY nao encontrada. Defina a variavel de ambiente "
                "ou use .env/.env.example/.env.ecample contendo: OPENAI_API_KEY=sk-..."
            )
        _client = OpenAI()
    return _client


def _normalize_label(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text)
    norm = "".join(ch for ch in norm if not unicodedata.combining(ch))
    return norm.lower().strip()


def classify_sub_assunto_llm(autos_text: str) -> str:
    """Classifies petition text as 'Golpe' or 'Genérico'.

    Raises on API/runtime errors so caller can apply fallback.
    """
    text = autos_text.strip()[:MAX_INPUT_CHARS]
    client = _get_client()
    resp = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        max_tokens=3,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    )
    answer = (resp.choices[0].message.content or "").strip()
    low = _normalize_label(answer)
    if "golpe" in low:
        return "Golpe"
    if "generico" in low:
        return "Genérico"
    raise ValueError(f"Resposta inesperada do modelo: {answer!r}")
