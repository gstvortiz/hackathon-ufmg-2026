from pathlib import Path
import argparse

import numpy as np
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


def build_sentencas_from_xlsx(xlsx_path: Path) -> pd.DataFrame:
    df_processos = pd.read_excel(
        xlsx_path,
        sheet_name='Resultados dos processos'
    )

    df_subsidios = pd.read_excel(
        xlsx_path,
        sheet_name='Subsídios disponibilizados'
    )

    df_subsidios.columns = df_subsidios.loc[0]
    df_subsidios = df_subsidios.drop(0).copy()
    df_subsidios = df_subsidios.rename(
        columns={'Número do processos': 'Número do processo'}
    )

    df = df_processos.merge(df_subsidios, on='Número do processo', how='left')

    subs_cols = [
        'Contrato',
        'Extrato',
        'Comprovante de crédito',
        'Dossiê',
        'Demonstrativo de evolução da dívida',
        'Laudo referenciado',
    ]

    for col in subs_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    if 'Valor da causa' in df.columns:
        df['Valor da causa'] = pd.to_numeric(df['Valor da causa'], errors='coerce')

    if 'Valor da condenação/indenização' in df.columns:
        df['Valor da condenação/indenização'] = pd.to_numeric(
            df['Valor da condenação/indenização'],
            errors='coerce'
        )

    df['A'] = np.where(df['Resultado micro'] == 'Acordo', 'A', '¬A')

    df['E'] = pd.Series(index=df.index, dtype='object')
    df.loc[
        (df['A'] == '¬A') & (df['Resultado macro'] == 'Êxito'),
        'E'
    ] = 'E'
    df.loc[
        (df['A'] == '¬A') & (df['Resultado macro'] == 'Não Êxito'),
        'E'
    ] = '¬E'

    df['α'] = np.nan
    mask_alpha = (
        (df['A'] == '¬A') &
        (df['E'] == '¬E') &
        (df['Valor da causa'] > 0) &
        (df['Valor da condenação/indenização'] >= 0)
    )

    df.loc[mask_alpha, 'α'] = (
        df.loc[mask_alpha, 'Valor da condenação/indenização'] /
        df.loc[mask_alpha, 'Valor da causa']
    )

    return df


def main():
    project_root = find_project_root(Path(__file__))
    data_dir = project_root / 'data'
    sentencas_path = data_dir / 'sentencas.csv'

    parser = argparse.ArgumentParser(
        description='Atualiza data/sentencas.csv a partir de um arquivo XLSX.'
    )
    parser.add_argument(
        '--xlsx',
        type=str,
        default=None,
        help='Caminho para o XLSX original com as abas '
             '"Resultados dos processos" e "Subsídios disponibilizados".'
    )

    args = parser.parse_args()

    if args.xlsx is None:
        print('Nenhum XLSX foi informado.')
        print(f'A base oficial atual continua sendo: {sentencas_path}')
        print('Para regenerar o sentencas.csv, rode por exemplo:')
        print(
            'python src/policy/training/merge.py '
            '--xlsx /caminho/para/Candidatos.xlsx'
        )
        return

    xlsx_path = Path(args.xlsx).expanduser().resolve()

    if not xlsx_path.exists():
        raise FileNotFoundError(f'XLSX não encontrado: {xlsx_path}')

    df = build_sentencas_from_xlsx(xlsx_path)
    sentencas_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(sentencas_path, index=False)

    print(f'sentencas.csv atualizado em: {sentencas_path}')
    print(f'XLSX de origem: {xlsx_path}')
    print(f'Total de linhas: {len(df)}')
    print(df['A'].value_counts(dropna=False))
    print(df['E'].value_counts(dropna=False))


if __name__ == '__main__':
    main()