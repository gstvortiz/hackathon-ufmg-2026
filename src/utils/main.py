import subprocess
import sys
from pathlib import Path
import pandas as pd


def find_project_root(start: Path) -> Path:
    start = start.resolve()
    for candidate in [start.parent, *start.parents]:
        if (candidate / 'data').exists() and (candidate / 'src').exists():
            return candidate
    raise FileNotFoundError(
        'Não foi possível localizar a raiz do projeto. '
        'Esperava encontrar as pastas data/ e src/.'
    )


def resolve_training_script(candidate_names, required_tokens) -> Path:
    for name in candidate_names:
        path = POLICY_TRAINING_DIR / name
        if path.exists():
            return path

    py_files = sorted(POLICY_TRAINING_DIR.glob('*.py'))
    for path in py_files:
        normalized = path.name.casefold().replace(' ', '')
        if all(token.casefold().replace(' ', '') in normalized for token in required_tokens):
            return path

    available = ', '.join(p.name for p in py_files) or '<nenhum .py>'
    raise FileNotFoundError(
        f'Nenhum script compatível encontrado em {POLICY_TRAINING_DIR}. '
        f'Esperado algo como {candidate_names}. Disponíveis: {available}'
    )


PROJECT_ROOT = find_project_root(Path(__file__))
POLICY_TRAINING_DIR = PROJECT_ROOT / 'src' / 'policy' / 'training'
MODELS_DIR = PROJECT_ROOT / 'src' / 'policy' / 'models'
MODEL_DIRS = [
    MODELS_DIR / 'classifiers',
    MODELS_DIR / 'expectations',
]
DATA_PATH = PROJECT_ROOT / 'data' / 'sentencas.csv'

scripts = [
    resolve_training_script(
        candidate_names=(
            'P(E | ¬A, X).py',
            'P(E _ ¬A, X).py',
            'P(E|¬A,X).py',
        ),
        required_tokens=('p(e', '¬a', 'x'),
    ),
    resolve_training_script(
        candidate_names=(
            'E[α | UF].py',
            'E[α _ UF].py',
            'E[α|UF].py',
        ),
        required_tokens=('e[', 'α', 'uf'),
    ),
    resolve_training_script(
        candidate_names=(
            'E[$|VT].py',
            'E[$_VT].py',
            'E[$ | VT].py',
        ),
        required_tokens=('e[', '$', 'vt'),
    ),
]


def clear_previous_models():
    removed_files = []

    for models_dir in MODEL_DIRS:
        if not models_dir.exists():
            continue

        for model_path in sorted(models_dir.glob('*.pkl')):
            model_path.unlink()
            removed_files.append(model_path)

    if removed_files:
        print('Modelos anteriores removidos:')
        for model_path in removed_files:
            print(f'- {model_path}')
    else:
        print('Nenhum modelo anterior encontrado para remover.')

if not DATA_PATH.exists():
    raise FileNotFoundError(f'Base não encontrada: {DATA_PATH}')

df = pd.read_csv(DATA_PATH)
if df.empty:
    raise RuntimeError('sentencas.csv está vazio.')

print(f'Base carregada com sucesso. sentencas.csv possui {len(df)} linhas.')
clear_previous_models()

for script in scripts:
    print(f'Rodando {script}...')
    result = subprocess.run([sys.executable, str(script)], cwd=str(PROJECT_ROOT))

    if result.returncode != 0:
        raise RuntimeError(f'Erro ao rodar {script}')
