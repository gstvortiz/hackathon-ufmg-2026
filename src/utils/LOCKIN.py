import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

from sklearn.metrics import confusion_matrix


class ExpectedAlphaByUF:
    def __init__(self):
        self.global_mean_ = None
        self.mean_by_uf_ = None
        self.feature_names_in_ = ['UF']
        self.target_name_ = 'α'

    def fit(self, X, y):
        X = X.copy()
        y = pd.Series(y).copy()

        if 'UF' not in X.columns:
            raise ValueError("X precisa conter a coluna 'UF'.")

        data = pd.concat([X[['UF']].copy(), y.rename(self.target_name_)], axis=1)
        data = data.dropna().copy()

        self.global_mean_ = data[self.target_name_].mean()
        self.mean_by_uf_ = (
            data.groupby('UF')[self.target_name_]
            .mean()
            .to_dict()
        )

        return self

    def predict(self, X):
        X = X.copy()

        if 'UF' not in X.columns:
            raise ValueError("X precisa conter a coluna 'UF'.")

        if self.global_mean_ is None or self.mean_by_uf_ is None:
            raise ValueError("O modelo ainda não foi treinado. Rode fit() antes de predict().")

        y_pred = X['UF'].map(self.mean_by_uf_).fillna(self.global_mean_)
        return y_pred.to_numpy()


def plot_confusion_matrices(y_true, y_pred, labels=None, figsize=(14, 5), cmap='Blues'):
    if labels is None:
        labels = sorted(pd.Series(y_true).dropna().unique())

    cm = confusion_matrix(y_true, y_pred, labels=labels)
    cm_norm = confusion_matrix(y_true, y_pred, labels=labels, normalize='pred')

    fig, axs = plt.subplots(1, 2, figsize=figsize)

    sns.heatmap(
        cm,
        annot=True,
        fmt='d',
        cmap=cmap,
        xticklabels=labels,
        yticklabels=labels,
        ax=axs[0]
    )
    axs[0].set_xlabel('Predito')
    axs[0].set_ylabel('Real')
    axs[0].set_title('Matriz de Confusão')

    sns.heatmap(
        cm_norm,
        annot=True,
        fmt='.2%',
        cmap=cmap,
        xticklabels=labels,
        yticklabels=labels,
        ax=axs[1]
    )
    axs[1].set_xlabel('Predito')
    axs[1].set_ylabel('Real')
    axs[1].set_title('Matriz de Confusão Normalizada por Predição')

    plt.tight_layout()

    return fig, axs


def discretize_by_quantiles_named(series, n_classes, prefix='Q'):
    valid = series.dropna().copy()

    raw_bins = pd.qcut(valid, q=n_classes, duplicates='drop')

    intervals = pd.DataFrame({
        'intervalo': raw_bins,
        'valor': valid
    })

    summary = (
        intervals
        .groupby('intervalo', as_index=False)
        .agg(
            minimo=('valor', 'min'),
            maximo=('valor', 'max'),
            contagem=('valor', 'size')
        )
        .sort_values('minimo')
        .reset_index(drop=True)
    )

    summary['proporcao'] = summary['contagem'] / summary['contagem'].sum()
    summary['classe'] = [
        f'{prefix}{i} [{row.minimo:.4f}, {row.maximo:.4f}]'
        for i, row in enumerate(summary.itertuples(index=False), start=1)
    ]

    intervalo_para_classe = {
        intervalo: classe
        for intervalo, classe in zip(summary['intervalo'], summary['classe'])
    }

    discretized = pd.Series(index=series.index, dtype='object')
    discretized.loc[valid.index] = raw_bins.map(intervalo_para_classe)

    summary = summary[['classe', 'minimo', 'maximo', 'contagem', 'proporcao']]

    return discretized, summary