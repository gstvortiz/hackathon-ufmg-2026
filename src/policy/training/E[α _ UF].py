from pathlib import Path
import sys
import pickle

import pandas as pd
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
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
MODELS_EXPECTATIONS_DIR = POLICY_DIR / 'models' / 'expectations'

sys.path.append(str(UTILS_DIR))

from LOCKIN import ExpectedAlphaByUF


pd.set_option('display.max_columns', None)
MODELS_EXPECTATIONS_DIR.mkdir(parents=True, exist_ok=True)

df = pd.read_csv(DATA_PATH)

X_cols = ['UF']
y_col = 'α'

data = df[X_cols + [y_col]].dropna().copy()
data['α'] = pd.to_numeric(data['α'], errors='coerce')
data = data.dropna().copy()

X = data[X_cols].copy()
y = data[y_col].copy()

X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.2,
    random_state=72
)

model = ExpectedAlphaByUF()
model.fit(X_train, y_train)

model_path = MODELS_EXPECTATIONS_DIR / 'E[α | UF].pkl'
with open(model_path, 'wb') as f:
    pickle.dump(model, f)

y_pred_alpha = model.predict(X_test)

mae = mean_absolute_error(y_test, y_pred_alpha)
rmse = root_mean_squared_error(y_test, y_pred_alpha)

print(f'Modelo salvo em: {model_path}')
print(f'MAE: {mae:.4f}')
print(f'RMSE: {rmse:.4f}')