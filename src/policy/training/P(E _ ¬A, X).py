from pathlib import Path
import sys
import pickle

import matplotlib.pyplot as plt
import pandas as pd
from catboost import CatBoostClassifier
from sklearn.model_selection import train_test_split


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
SRC_DIR = PROJECT_ROOT / 'src'
UTILS_DIR = SRC_DIR / 'utils'
POLICY_DIR = SRC_DIR / 'policy'
DATA_PATH = PROJECT_ROOT / 'data' / 'sentencas.csv'
MODELS_CLASSIFIERS_DIR = POLICY_DIR / 'models' / 'classifiers'

sys.path.append(str(UTILS_DIR))

from LOCKIN import plot_confusion_matrices


pd.set_option('display.max_columns', None)
MODELS_CLASSIFIERS_DIR.mkdir(parents=True, exist_ok=True)

df = pd.read_csv(DATA_PATH)

X_cols_processos = ['UF']
X_cols_subsidio = [
    'Contrato',
    'Extrato',
    'Comprovante de crédito',
    'Dossiê',
    'Demonstrativo de evolução da dívida',
    'Laudo referenciado',
]

X_cols = X_cols_processos + X_cols_subsidio
y_col = 'E'

data = df[X_cols + [y_col]].dropna().copy()

for col in X_cols_subsidio:
    data[col] = pd.to_numeric(data[col], errors='coerce')

data = data.dropna().copy()

X = data[X_cols].copy()
y = data[y_col].copy()

X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    stratify=y,
    test_size=0.2,
    random_state=42
)

catboost = CatBoostClassifier(
    cat_features=X_cols_processos,
    random_state=72,
    verbose=0
)

catboost.fit(X_train, y_train)

model_path = MODELS_CLASSIFIERS_DIR / 'P(E | ¬A, X).pkl'
with open(model_path, 'wb') as f:
    pickle.dump(catboost, f)

print(f'Modelo salvo em: {model_path}')

y_pred = catboost.predict(X_test)

fig, axs = plot_confusion_matrices(
    y_test,
    y_pred,
    labels=['¬E', 'E'],
    figsize=(12, 5)
)

plt.show()