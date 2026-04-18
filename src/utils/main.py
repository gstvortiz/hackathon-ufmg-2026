import subprocess
import sys
from pathlib import Path
import pandas as pd


def find_project_root(start: Path) -> Path:
    start = start.resolve()
    for candidate in [start.parent, *start.parents]:
        if (candidate / 'data' / 'sentencas.csv').exists() and (candidate / 'src').exists():
            return candidate
    raise FileNotFoundError(
        'Não foi possível localizar a raiz do projeto. '
        'Esperava encontrar data/sentencas.csv.'
    )


PROJECT_ROOT = find_project_root(Path(__file__))
POLICY_TRAINING_DIR = PROJECT_ROOT / 'src' / 'policy' / 'training'
DATA_PATH = PROJECT_ROOT / 'data' / 'sentencas.csv'

scripts = [
    POLICY_TRAINING_DIR / 'P(E | ¬A, X).py',
    POLICY_TRAINING_DIR / 'E[α | UF].py',
    POLICY_TRAINING_DIR / 'E[$|VT].py',
]

if not DATA_PATH.exists():
    raise FileNotFoundError(f'Base não encontrada: {DATA_PATH}')

df = pd.read_csv(DATA_PATH)
if df.empty:
    raise RuntimeError('sentencas.csv está vazio.')

print(f'Base carregada com sucesso. sentencas.csv possui {len(df)} linhas.')

for script in scripts:
    print(f'Rodando {script}...')
    result = subprocess.run([sys.executable, str(script)], cwd=str(PROJECT_ROOT))

    if result.returncode != 0:
        raise RuntimeError(f'Erro ao rodar {script}')