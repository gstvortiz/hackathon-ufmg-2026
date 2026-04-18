# Setup e Execução

Este documento descreve a forma correta de instalar, configurar e executar o MVP **JurisIA** com base no código atual do repositório.

## Execução rápida

Se o objetivo é apenas rodar a aplicação web, o processo é este:

```bash
conda env create -f environment.yml
conda activate enter
pip install -r src/interface/requirements_web.txt
python -m src.interface.web_server
```

### Retreinar tudo

```bash
cd Enter
conda activate enter
python src/policy/training/merge.py --xlsx /caminho/para/base.xlsx
python src/utils/main.py
```
