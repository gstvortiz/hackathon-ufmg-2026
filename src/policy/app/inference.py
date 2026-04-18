from pathlib import Path
import sys
import pickle
import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.tools.sm_exceptions import DomainWarning


def find_project_root(start: Path) -> Path:
    start = start.resolve()

    for candidate in [start.parent, *start.parents]:
        if (
            (candidate / 'src' / 'policy').exists() and
            (candidate / 'src' / 'utils').exists()
        ):
            return candidate

    raise FileNotFoundError(
        'Não foi possível localizar a raiz do projeto. '
        'Esperava encontrar src/policy e src/utils.'
    )


PROJECT_ROOT = find_project_root(Path(__file__))
SRC_DIR = PROJECT_ROOT / 'src'
UTILS_DIR = SRC_DIR / 'utils'
POLICY_DIR = SRC_DIR / 'policy'

sys.path.append(str(UTILS_DIR))

from LOCKIN import ExpectedAlphaByUF


warnings.filterwarnings('ignore', category=DomainWarning)

MODELS_CLASSIFIERS_DIR = POLICY_DIR / 'models' / 'classifiers'
MODELS_EXPECTATIONS_DIR = POLICY_DIR / 'models' / 'expectations'

FEATURES_E = [
    'UF',
    'Contrato',
    'Extrato',
    'Comprovante de crédito',
    'Dossiê',
    'Demonstrativo de evolução da dívida',
    'Laudo referenciado',
]

FEATURES_VT = ['Valor da causa']
MODEL_VT_PATH = MODELS_EXPECTATIONS_DIR / 'E[$|VT].pkl'


def gamma_rvs_from_mu_phi(mu, phi, rng):
    mu = np.asarray(mu, dtype=float)
    phi = float(phi)

    if np.any(mu <= 0):
        raise ValueError('O modelo gerou médias <= 0, inválidas para Gamma.')
    if not np.isfinite(phi) or phi <= 0:
        raise ValueError('phi inválido para Gamma.')

    shape = 1.0 / phi
    scale = phi * mu
    return rng.gamma(shape=shape, scale=scale, size=mu.shape)


def predict_pi_gamma_from_saved_model(
    x,
    model_path=MODEL_VT_PATH,
    n_boot=2000,
    alpha=0.05,
    seed=42,
    max_tries=None,
):
    rng = np.random.default_rng(seed)

    with open(model_path, 'rb') as f:
        result = pickle.load(f)

    X_train = np.asarray(result.model.exog, dtype=float)

    x = np.asarray(x, dtype=float).reshape(1, -1)
    if x.shape[1] == X_train.shape[1]:
        X_pred = x
    else:
        X_pred = sm.add_constant(x, has_constant='add')

    pred = float(result.predict(X_pred)[0])
    phi_hat = float(result.scale)
    mu_hat_train = np.asarray(result.predict(X_train), dtype=float)

    if pred <= 0:
        raise ValueError('A previsão pontual ficou <= 0, inválida para Gamma.')

    if np.any(mu_hat_train <= 0):
        raise ValueError('O ajuste original gerou médias <= 0.')

    boot_ynew = []
    n_tries = 0
    max_tries = max_tries or (10 * n_boot)

    while len(boot_ynew) < n_boot and n_tries < max_tries:
        n_tries += 1
        y_star = gamma_rvs_from_mu_phi(mu_hat_train, phi_hat, rng)

        try:
            result_star = sm.GLM(
                y_star,
                X_train,
                family=sm.families.Gamma(link=sm.families.links.Identity()),
            ).fit()
        except Exception:
            continue

        phi_star = float(result_star.scale)
        mu_star_pred = float(result_star.predict(X_pred)[0])

        if (
            not np.isfinite(phi_star)
            or phi_star <= 0
            or not np.isfinite(mu_star_pred)
            or mu_star_pred <= 0
        ):
            continue

        y_new_star = float(
            gamma_rvs_from_mu_phi(np.array([mu_star_pred]), phi_star, rng)[0]
        )
        boot_ynew.append(y_new_star)

    if len(boot_ynew) == 0:
        raise RuntimeError('Nenhum bootstrap válido foi obtido.')

    lower = float(np.quantile(boot_ynew, alpha / 2))
    upper = float(np.quantile(boot_ynew, 1 - alpha / 2))

    return pred, lower, upper


def load_models():
    with open(MODELS_CLASSIFIERS_DIR / 'P(E | ¬A, X).pkl', 'rb') as f:
        model_e = pickle.load(f)

    with open(MODELS_EXPECTATIONS_DIR / 'E[α | UF].pkl', 'rb') as f:
        model_alpha = pickle.load(f)

    return model_e, model_alpha


def predict_case(case_dict):
    model_e, model_alpha = load_models()

    df_case = pd.DataFrame([case_dict])

    df_case_e = df_case.reindex(columns=FEATURES_E).copy()
    for col in FEATURES_E[1:]:
        df_case_e[col] = pd.to_numeric(df_case_e[col], errors='coerce')

    proba_e = model_e.predict_proba(df_case_e)[0]
    classes_e = model_e.classes_

    idx_e = list(classes_e).index('E')
    p_e = proba_e[idx_e]

    alpha_pred = model_alpha.predict(df_case_e[['UF']])[0]

    df_case_vt = df_case.reindex(columns=FEATURES_VT).copy()
    df_case_vt['Valor da causa'] = pd.to_numeric(
        df_case_vt['Valor da causa'],
        errors='coerce'
    )

    valor_pred = None
    valor_lower = None
    valor_upper = None
    valor_causa = df_case_vt['Valor da causa'].iloc[0]

    if pd.notna(valor_causa) and valor_causa > 0:
        valor_pred, valor_lower, valor_upper = predict_pi_gamma_from_saved_model(
            x=[valor_causa],
            model_path=MODEL_VT_PATH
        )

    return {
        'P(E | ¬A, X)': p_e,
        'E[α | UF]': alpha_pred,
        'E[VP | A, VT]': valor_pred,
        '[VP | A, VT]_lower': valor_lower,
        '[VP | A, VT]_upper': valor_upper
    }