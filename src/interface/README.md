# Interface Web (Frontend + Backend)

Este módulo adiciona a arquitetura do site (frontend + backend) integrada aos modelos já existentes em `src/policy/app/inference.py`.

## Estrutura

```text
src/interface/
├── web_server.py                 # backend Flask principal
├── document_extractor.py         # extração de dados dos PDFs (autos + subsídios)
├── management_report.py          # geração de relatório gerencial via SQLite/OpenAI
├── llm_subtopic.py               # classificador opcional de sub-assunto (LLM)
├── requirements_web.txt          # dependências mínimas
├── requirements_web_full.txt     # dependências completas
└── templates/
    ├── analise.html              # página principal de análise
    └── painel_lancamentos.html   # página de lançamentos/feedback
```

## Pré-requisitos

- Python 3.10+
- Modelos treinados presentes em:
  - `src/policy/models/classifiers/P(E | ¬A, X).pkl`
  - `src/policy/models/expectations/E[α | UF].pkl`
  - `src/policy/models/expectations/E[$|VT].pkl`

## Instalação

Na raiz do repositório:

```bash
pip install -r src/interface/requirements_web.txt
```

Opcional (stack completa):

```bash
pip install -r src/interface/requirements_web_full.txt
```

## Variáveis de ambiente (opcional)

```env
OPENAI_API_KEY=sk-...
OPENAI_DECISION_MODEL=gpt-4o-mini
OPENAI_REPORT_MODEL=gpt-4o-mini
JURIS_DB_PATH=src/interface/juris_ia.db
PORT=5000
FLASK_DEBUG=true
```

Observação:
- Sem `OPENAI_API_KEY`, o sistema continua funcionando com textos de fallback local para justificativas/relatórios.
- O carregamento de ambiente busca automaticamente `.env`, `.env.example` (e também `.env.ecample`) na raiz do projeto e em `src/interface/`.

## Execução

Na raiz do repositório:

```bash
python -m src.interface.web_server
```

Depois acesse:
- `http://localhost:5000/` (nova análise)
- `http://localhost:5000/lancamentos` (painel gerencial)

## Fluxo resumido

1. Upload dos PDFs na tela principal.
2. `document_extractor.py` classifica e extrai `número do processo`, `UF` e `valor da causa`.
3. `web_server.py` monta `case_dict` e chama `predict_case` de `src/policy/app/inference.py`.
4. Sistema calcula recomendação (`ACORDO` ou `DEFESA`) e valores esperados.
5. Análise pode ser confirmada e gravada no SQLite (`analises`, `analises_feedback`).
