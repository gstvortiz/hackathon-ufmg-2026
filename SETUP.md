# Setup e Execucao

Este documento descreve como instalar, configurar e executar o MVP **JurisIA** com base no codigo atual do repositorio.

## Visao rapida

O projeto possui dois fluxos principais:

- **Uso do MVP web**: subir a interface Flask e analisar casos com os modelos ja presentes no repositorio.
- **Treino/atualizacao dos modelos**: gerar `data/sentencas.csv` a partir da base original e executar os scripts de treino.

Se o seu objetivo e apenas demonstrar ou usar a aplicacao, o caminho mais rapido e o primeiro.

## Pre-requisitos

- `Python 3.10`
- `conda` ou `miniconda` para criar o ambiente a partir de `environment.yml`
- acesso a terminal na raiz do projeto
- opcionalmente, uma chave `OPENAI_API_KEY` para habilitar:
  - justificativa textual da recomendacao
  - relatorio gerencial com IA

## Estrutura relevante

```text
Enter/
├── environment.yml
├── .env.example
├── SETUP.md
├── README.md
├── data/
├── src/
│   ├── interface/
│   │   ├── web_server.py
│   │   ├── requirements_web.txt
│   │   └── templates/
│   ├── policy/
│   │   ├── app/
│   │   ├── training/
│   │   └── models/
│   └── utils/
└── docs/
```

## 1. Instalacao

Na pasta do projeto:

```bash
cd Enter
conda env create -f environment.yml
conda activate enter
pip install -r src/interface/requirements_web.txt
```

Observacoes:

- `environment.yml` instala as dependencias de ciencia de dados e treino, incluindo `catboost`.
- `src/interface/requirements_web.txt` instala as dependencias da interface Flask, leitura de PDFs e OpenAI.
- Se preferir dependencias totalmente pinadas para a interface, use `src/interface/requirements_web_full.txt` no lugar do arquivo minimo.

## 2. Variaveis de ambiente

Existe um arquivo base em [`.env.example`](./.env.example). Copie-o para `.env`:

```bash
cp .env.example .env
```

Preencha conforme necessario. Exemplo recomendado:

```env
OPENAI_API_KEY=sk-...
OPENAI_DECISION_MODEL=gpt-4o-mini
OPENAI_REPORT_MODEL=gpt-4o-mini
JURIS_DB_PATH=src/interface/juris_ia.db
PORT=5000
FLASK_DEBUG=true
SECRET_KEY=juris-ia-local-dev
PENDING_ANALISE_TTL_SECONDS=7200
MAX_PENDING_ANALISES=500
```

Explicacao das variaveis:

- `OPENAI_API_KEY`: habilita justificativa da recomendacao e relatorio gerencial via OpenAI.
- `OPENAI_DECISION_MODEL`: modelo usado na explicacao da recomendacao.
- `OPENAI_REPORT_MODEL`: modelo usado no relatorio gerencial.
- `JURIS_DB_PATH`: caminho do banco SQLite usado pela interface.
- `PORT`: porta do servidor Flask.
- `FLASK_DEBUG`: ativa modo debug.
- `SECRET_KEY`: chave da aplicacao Flask.
- `PENDING_ANALISE_TTL_SECONDS`: tempo de expiracao de analises pendentes antes da confirmacao.
- `MAX_PENDING_ANALISES`: limite de analises pendentes armazenadas.

Importante:

- Sem `OPENAI_API_KEY`, a aplicacao continua funcionando.
- Nesse caso, a justificativa usa fallback local e o endpoint de relatorio gerencial com IA nao funcionara.
- Nunca versione um `.env` com credenciais reais.

## 3. Execucao rapida do MVP web

Com o ambiente ativo:

```bash
python -m src.interface.web_server
```

Depois acesse:

- `http://localhost:5000/` para nova analise
- `http://localhost:5000/lancamentos` para painel gerencial

O servidor cria automaticamente o banco SQLite na primeira execucao.

## 4. O que ja vem pronto no repositorio

O repositorio ja inclui artefatos para facilitar a execucao do MVP:

- modelos serializados em `src/policy/models/`
- interface web em Flask
- templates HTML prontos
- pipeline de extracao/classificacao de documentos

Isso significa que, para subir a interface, **voce nao precisa treinar os modelos antes**.

Mesmo se houver falha ao carregar `inference.py` ou os modelos, o backend tem um fallback dummy para nao impedir a demonstracao da interface, embora a analise deixe de refletir o modelo estatistico treinado.

## 5. Como usar a interface

### Tela principal

Na rota `/`, o usuario pode enviar:

- `Autos` (obrigatorio)
- `Contrato`
- `Extrato`
- `Comprovante`
- `Dossie`
- `Demonstrativo`
- `Laudo`

O sistema:

1. verifica se os arquivos sao PDFs;
2. extrai texto dos documentos;
3. classifica o tipo documental;
4. extrai dos Autos:
   - numero do processo
   - UF
   - valor da causa
5. monta o `case_dict`;
6. executa os modelos;
7. calcula a recomendacao entre `ACORDO` e `DEFESA`;
8. gera a justificativa;
9. salva a analise somente apos confirmacao do usuario.

### Painel gerencial

Na rota `/lancamentos`, o sistema permite:

- consultar analises gravadas;
- editar campos da tabela `analises`;
- registrar feedback final do caso em `analises_feedback`;
- calcular metricas gerenciais;
- solicitar relatorio gerencial via OpenAI.

## 6. Endpoints uteis

Rotas principais da aplicacao:

- `GET /`
- `GET /lancamentos`
- `POST /analisar`
- `POST /api/confirmar-analise`
- `GET /api/lancamentos`
- `PATCH /api/lancamentos/<id>`
- `POST /api/feedback`
- `GET /api/eficacia`
- `POST /api/relatorio-ia`
- `GET /health`

Teste rapido de health check:

```bash
curl http://localhost:5000/health
```

## 7. Banco de dados

O backend usa SQLite e cria as tabelas automaticamente:

- `analises`
- `analises_feedback`
- `analises_pendentes`

Por padrao, o banco fica em:

```text
src/interface/juris_ia.db
```

Se quiser alterar, defina `JURIS_DB_PATH` no `.env`.

## 8. Dados

Para apenas executar a interface, a pasta `data/` nao e obrigatoria.

Ela passa a ser necessaria quando voce quiser:

- reconstruir `data/sentencas.csv`
- retreinar os modelos

Consulte [`data/README.md`](./data/README.md) para a estrutura esperada.

## 9. Atualizacao da base de treino

Se voce recebeu o arquivo XLSX original com as abas:

- `Resultados dos processos`
- `Subsídios disponibilizados`

gere o CSV consolidado com:

```bash
python src/policy/training/merge.py --xlsx /caminho/para/base.xlsx
```

Isso atualiza:

```text
data/sentencas.csv
```

## 10. Treino dos modelos

Depois de garantir que `data/sentencas.csv` existe, rode:

```bash
python src/utils/main.py
```

Esse script executa automaticamente:

- `src/policy/training/P(E _ ¬A, X).py`
- `src/policy/training/E[α _ UF].py`
- `src/policy/training/E[$_VT].py`

Os modelos gerados sao salvos em:

```text
src/policy/models/classifiers/P(E | ¬A, X).pkl
src/policy/models/expectations/E[α | UF].pkl
src/policy/models/expectations/E[$|VT].pkl
```

Observacao:

- Use `python src/utils/main.py` em vez de chamar os scripts manualmente, porque os nomes dos arquivos de treino contem caracteres especiais.

## 11. Teste simples da inferencia

Para verificar a inferencia diretamente pelo terminal:

```bash
python src/policy/app/app.py
```

Esse script monta um `case_dict` de exemplo e imprime:

- `P(E | ¬A, X)`
- `E[α | UF]`
- `E[VP | A, VT]`
- `E(VP | ¬A, X)`

## 12. Solucao de problemas

### Erro ao extrair texto do PDF

Possiveis causas:

- PDF escaneado sem OCR
- PDF corrompido
- documento sem texto selecionavel

Nesse caso, tente um PDF com OCR ou melhor qualidade.

### Erro de classificacao documental

O classificador atual usa heuristicas locais em `src/interface/document_extractor.py`. Se o layout do documento fugir muito do padrao esperado, a analise pode ser bloqueada.

### Relatorio IA falhando

Verifique:

- se `OPENAI_API_KEY` foi definida
- se o pacote `openai` esta instalado
- se ha conectividade de rede

### Banco em local diferente

Defina no `.env`:

```env
JURIS_DB_PATH=/caminho/desejado/juris_ia.db
```

## 13. Comandos resumidos

### Subir a interface

```bash
cd Enter
conda env create -f environment.yml
conda activate enter
pip install -r src/interface/requirements_web.txt
cp .env.example .env
python -m src.interface.web_server
```

### Retreinar tudo

```bash
cd Enter
conda activate enter
python src/policy/training/merge.py --xlsx /caminho/para/base.xlsx
python src/utils/main.py
```

## 14. Observacoes finais

- O `README.md` principal descreve a arquitetura e a abordagem do produto em mais detalhe.
- O modulo `src/interface/README.md` traz um resumo rapido focado na interface web.
- O setup atual e suficiente para um MVP de hackathon; para producao, o projeto ainda precisaria de autenticacao, observabilidade, OCR mais robusto e banco transacional mais apropriado.
