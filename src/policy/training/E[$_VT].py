from pathlib import Path
import pickle
import warnings

import pandas as pd
import seaborn as sns
import statsmodels.api as sm
from sklearn.metrics import mean_absolute_error, root_mean_squared_error
from sklearn.model_selection import train_test_split
from statsmodels.tools.sm_exceptions import DomainWarning


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
POLICY_DIR = SRC_DIR / 'policy'
DATA_PATH = PROJECT_ROOT / 'data' / 'sentencas.csv'
MODELS_EXPECTATIONS_DIR = POLICY_DIR / 'models' / 'expectations'

warnings.filterwarnings('ignore', category=DomainWarning)
pd.set_option('display.max_columns', None)
MODELS_EXPECTATIONS_DIR.mkdir(parents=True, exist_ok=True)

df = pd.read_csv(DATA_PATH)

X_cols = ['Valor da causa']
y_col = 'Valor da condenação/indenização'

data = df.loc[df['Resultado micro'] == 'Acordo', X_cols + [y_col]].dropna().copy()

for col in X_cols + [y_col]:
    data[col] = pd.to_numeric(data[col], errors='coerce')

data = data.dropna().copy()
data = data[(data['Valor da causa'] > 0) & (data[y_col] > 0)].copy()

X = data[X_cols].copy()
y = data[y_col].copy()

X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.2,
    random_state=72
)

X_train_const = sm.add_constant(X_train, has_constant='add')
X_test_const = sm.add_constant(X_test, has_constant='add')

model = sm.GLM(
    y_train,
    X_train_const,
    family=sm.families.Gamma(link=sm.families.links.Identity()),
)

result = model.fit()

model_path = MODELS_EXPECTATIONS_DIR / 'E[$|VT].pkl'
with open(model_path, 'wb') as f:
    pickle.dump(result, f)

y_pred_valor = result.predict(X_test_const)

sns.regplot(x=y_test, y=y_pred_valor, line_kws={'color': 'red'})

mae = mean_absolute_error(y_test, y_pred_valor)
rmse = root_mean_squared_error(y_test, y_pred_valor)

print(f'Modelo salvo em: {model_path}')
print(f'MAE: {mae:.4f}')
print(f'RMSE: {rmse:.4f}')