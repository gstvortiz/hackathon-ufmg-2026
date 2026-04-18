# Diagrama de Arquitetura da Solucao

Este documento descreve a arquitetura do **JurisIA** com base no codigo atual do repositorio.

## Visao geral

O sistema e composto por sete blocos principais:

- **Frontend web** em HTML/Tailwind, servido pelo Flask
- **Backend Flask** que orquestra validacao, inferencia, persistencia e relatorios
- **Camada de extracao documental** para classificar PDFs e extrair campos dos Autos
- **Camada de modelos estatisticos** para calcular custo esperado de acordo e defesa
- **Persistencia e monitoramento** em SQLite, com apoio opcional da OpenAI para explicacoes textuais
- **Camada opcional de IA generativa** para justificativas e relatorio gerencial
- **Pipeline de preparo e treino** para gerar a base consolidada e treinar os modelos

## Diagrama principal

```mermaid
flowchart LR
    U["Advogado / Usuario"]

    subgraph FE["Frontend Web"]
        T1["analise.html"]
        T2["painel_lancamentos.html"]
    end

    subgraph BE["Backend Flask - src/interface/web_server.py"]
        R1["Rotas de pagina<br/>/ e /lancamentos"]
        R2["API de analise<br/>/analisar"]
        R3["API de persistencia<br/>/api/confirmar-analise"]
        R4["APIs gerenciais<br/>/api/lancamentos<br/>/api/feedback<br/>/api/eficacia<br/>/api/relatorio-ia"]
        ORQ["Orquestracao de negocio<br/>validacao + decisao + metricas"]
    end

    subgraph DOC["Extracao e Validacao Documental"]
        DE["document_extractor.py"]
        PDF["pdfplumber"]
        REGEX["Classificacao por regex e padroes<br/>extract_numero_processo<br/>extract_uf<br/>extract_valor_causa"]
    end

    subgraph POL["Camada de Politica / Modelos"]
        INF["inference.py"]
        M1["Modelo de exito sem acordo<br/>CatBoost"]
        M2["Estimativa media por UF<br/>alpha"]
        M3["Modelo de valor esperado do acordo<br/>GLM Gamma"]
        DMY["Fallback dummy<br/>se inference falhar"]
    end

    subgraph DB["Persistencia"]
        SQL[("SQLite<br/>juris_ia.db")]
        A1["analises"]
        A2["analises_feedback"]
        A3["analises_pendentes"]
    end

    subgraph IA["Camada opcional OpenAI"]
        O1["Justificativa da recomendacao"]
        O2["Relatorio gerencial"]
    end

    subgraph TRAIN["Treino e Preparacao de Dados"]
        MG["merge.py"]
        TR["Scripts de treino<br/>src/policy/training"]
        UT["src/utils/main.py"]
        CSV["data/sentencas.csv"]
    end

    U --> T1
    U --> T2

    T1 --> R1
    T2 --> R1
    T1 --> R2
    T2 --> R4

    R2 --> ORQ
    R3 --> ORQ
    R4 --> ORQ

    ORQ --> DE
    DE --> PDF
    DE --> REGEX

    ORQ --> INF
    INF --> M1
    INF --> M2
    INF --> M3
    ORQ -. "fallback" .-> DMY

    ORQ --> SQL
    SQL --> A1
    SQL --> A2
    SQL --> A3

    ORQ --> O1
    ORQ --> O2

    MG --> CSV
    CSV --> TR
    UT --> TR
    TR --> M1
    TR --> M2
    TR --> M3
```

## Fluxo de analise de um caso

```mermaid
sequenceDiagram
    participant User as Advogado
    participant UI as Tela de analise
    participant API as Flask analisar
    participant DOC as document_extractor.py
    participant INF as inference.py
    participant DB as SQLite
    participant LLM as OpenAI opcional

    User->>UI: Envia Autos e subsidios
    UI->>API: POST /analisar
    API->>DOC: Ler PDFs + classificar documentos
    DOC-->>API: numero_processo, UF, valor_causa, docs_binarios
    API->>INF: predict_case(case_dict)
    INF-->>API: probabilidades e valores esperados
    API->>API: Calcula custo esperado sem acordo
    API->>API: Decide entre ACORDO e DEFESA
    API->>LLM: Gera justificativa textual se OpenAI estiver habilitada
    LLM-->>API: Justificativa em Markdown ou fallback local
    API-->>UI: Resultado da analise + token pendente
    User->>UI: Confirma gravacao
    UI->>API: POST /api/confirmar-analise
    API->>DB: Salva em analises e analises_feedback
    DB-->>API: analise_id
    API-->>UI: Confirmacao de persistencia
```

## Fluxo gerencial e de feedback

```mermaid
flowchart TD
    P["Usuario no painel /lancamentos"]
    L1["GET /api/lancamentos"]
    L2["POST /api/feedback"]
    L3["GET /api/eficacia"]
    L4["POST /api/relatorio-ia"]
    DB[("SQLite")]
    MET["calcular_metricas_gerenciais"]
    OAI["OpenAI opcional"]

    P --> L1
    P --> L2
    P --> L3
    P --> L4

    L1 --> DB
    L2 --> DB
    L3 --> MET
    L4 --> MET
    MET --> DB
    L4 --> OAI
    OAI --> L4
```

## Mapeamento de componentes para arquivos

| Componente | Arquivo principal | Responsabilidade |
|---|---|---|
| Frontend de analise | `src/interface/templates/analise.html` | Upload dos documentos, exibicao da recomendacao e confirmacao |
| Frontend gerencial | `src/interface/templates/painel_lancamentos.html` | Consulta de analises, feedback e KPIs |
| Backend principal | `src/interface/web_server.py` | Rotas Flask, regras de negocio, persistencia e integracao com OpenAI |
| Extracao documental | `src/interface/document_extractor.py` | Classificacao documental e extracao de campos dos Autos |
| Relatorio offline/auxiliar | `src/interface/management_report.py` | Geracao de metricas e relatorio gerencial fora da interface |
| Classificacao LLM opcional | `src/interface/llm_subtopic.py` | Classificacao complementar de sub-assunto |
| Inferencia estatistica | `src/policy/app/inference.py` | Carregamento de modelos e predicao |
| Exemplo de execucao local | `src/policy/app/app.py` | Teste simples da inferencia |
| Treino de P(E) | `src/policy/training/P(E _ ¬A, X).py` | Classificador de exito sem acordo |
| Treino de E alpha por UF | `src/policy/training/E[α _ UF].py` | Estimador medio por UF |
| Treino de E VP no acordo por VT | `src/policy/training/E[$_VT].py` | Modelo Gamma para valor esperado do acordo |
| Consolidacao da base | `src/policy/training/merge.py` | Gera `data/sentencas.csv` a partir do XLSX |
| Orquestrador do treino | `src/utils/main.py` | Executa os scripts de treino em sequencia |

## Decisao de negocio implementada

O backend segue esta logica:

- `E(VP | A)` vem do modelo de acordo
- `P(E | not A, X)` vem do classificador
- `E[alpha | UF]` estima a fracao paga quando nao ha exito
- `E(VP | not A, X) = (1 - P(E | not A, X)) * E[alpha | UF] * VT`
- a recomendacao final escolhe o menor custo esperado

## Observacoes sobre a arquitetura atual

- A arquitetura e adequada para MVP e demonstracao de hackathon.
- O backend centraliza muitas responsabilidades em `web_server.py`; uma evolucao natural seria separar servicos, repositorios e casos de uso.
- A persistencia em SQLite simplifica a demo, mas pode ser trocada por Postgres em um ambiente multiusuario.
- A camada OpenAI e opcional e desacoplada do fluxo minimo, o que ajuda na resiliencia do sistema.
