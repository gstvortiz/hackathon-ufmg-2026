# Coloque aqui o código-fonte da sua solução.

Não há restrição de linguagem ou tecnologia — use o que sua equipe domina melhor.

## Sugestões de organização

```
src/
├── policy/        # lógica da política de acordos (regras de decisão, sugestão de valor)
├── interface/     # interface de acesso do advogado à recomendação
└── utils/         # utilitários compartilhados
```

> Sinta-se livre para reorganizar conforme a arquitetura da sua solução.

## Estrutura Atual da Interface Web

```
src/interface/
├── web_server.py                 # backend Flask (rotas + integrações)
├── document_extractor.py         # extração/classificação de PDFs
├── management_report.py          # script de relatório gerencial
├── llm_subtopic.py               # classificação opcional de sub-assunto via LLM
├── requirements_web.txt          # dependências mínimas da interface
├── requirements_web_full.txt     # dependências completas da interface
└── templates/
    ├── analise.html              # tela de nova análise
    └── painel_lancamentos.html   # painel de lançamentos e feedback
```
