from inference import predict_case


if __name__ == '__main__':
    case_dict = {
        'UF': 'MG',
        'Contrato': 1,
        'Extrato': 1,
        'Comprovante de crédito': 1,
        'Dossiê': 1,
        'Demonstrativo de evolução da dívida': 1,
        'Laudo referenciado': 1,
        'Valor da causa': 10000,
    }

    resultado = predict_case(case_dict)
    valor_da_causa = case_dict['Valor da causa']

    resultado['E[VP | ¬A, X]'] = (
        (1 - resultado['P(E | ¬A, X)']) *
        resultado['E[α | UF]'] *
        valor_da_causa
    )

    print('Resultado da inferência:')
    for chave, valor in resultado.items():
        print(f'{chave}: {valor}')