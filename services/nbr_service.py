import os
import re
import pandas as pd
from utils.formatters import remover_acentos, normalizar_para_comparacao

# Números das colunas do Quadro II oficial da NBR 12.721. O conversor que gerou o
# consolidado.xlsx deixou essa "régua" vazar como linha de dados em algumas abas.
_COLUNAS_QUADRO_NBR = ['19', '23', '24', '28', '29', '37', '38']

def _linha_nbr_e_artefato(valores):
    """Filtra linhas-artefato conhecidas do conversor que gerou o consolidado NBR:
    - a régua de colunas do Quadro II oficial (19/23/24/28/29/37/38) que vazou como dado;
    - linhas cujo conteúdo numérico é todo zero (ex.: tabela de VAGAS zerada da Viena
      Violeta), que não informam nada e poderiam induzir a IA a validar contra 'vaga 0'."""
    if valores[-7:] == _COLUNAS_QUADRO_NBR:
        return True
    numericos = [v for v in valores if re.fullmatch(r'-?\d+(\.\d+)?', v)]
    if numericos and all(float(v) == 0 for v in numericos):
        # Só descarta se, além dos zeros, a linha tiver no máximo rótulos iniciais
        # (ex.: "Casa 41A - 1A | 0 | 0 | 0 | 0"). Linhas com áreas reais nunca caem aqui.
        if len(valores) - len(numericos) <= 2:
            return True
    return False

def _formatar_celula_nbr(valor):
    """Converte uma célula do consolidado NBR em texto limpo (corta ruído de float
    do pandas, tipo 53.43000000000001 -> '53.43', preservando casas reais como 60.0914)."""
    if isinstance(valor, float):
        if valor.is_integer():
            return str(int(valor))
        return f"{valor:.4f}".rstrip('0').rstrip('.')
    return str(valor).strip()

def carregar_nbr_consolidado(caminho_nbr):
    """Lê o consolidado NBR 12.721 (áreas e vagas por unidade) UMA única vez, no início.
    Cada aba (exceto MAPA) vira uma entrada {aba, nome_empreendimento, incorporador_nome, texto},
    onde 'texto' é a aba inteira renderizada linha a linha (informações preliminares,
    QUADRO II de áreas e tabela de VAGAS). Se o arquivo não existir ou falhar a leitura,
    retorna lista vazia e a auditoria segue normalmente sem o cruzamento de NBR."""
    if not os.path.exists(caminho_nbr):
        print(f"[AVISO] Planilha NBR não encontrada em {caminho_nbr} — auditoria seguirá sem cruzamento de áreas/vagas.")
        return []
    try:
        abas = pd.read_excel(caminho_nbr, sheet_name=None, header=None)
    except Exception as e:
        print(f"[AVISO] Falha ao ler a planilha NBR ({e}) — auditoria seguirá sem cruzamento de áreas/vagas.")
        return []

    entradas = []
    for nome_aba, df_aba in abas.items():
        if remover_acentos(nome_aba).strip().upper() == 'MAPA':
            continue
        linhas = []
        info = {'nome_empreendimento': '', 'incorporador_nome': ''}
        for _, linha in df_aba.iterrows():
            valores = [_formatar_celula_nbr(v) for v in linha.tolist() if pd.notna(v)]
            valores = [v for v in valores if v]
            if not valores or _linha_nbr_e_artefato(valores):
                continue
            chave = remover_acentos(valores[0]).strip().lower()
            if chave in info and len(valores) > 1:
                info[chave] = valores[1]
            linhas.append(' | '.join(valores))
        if not linhas:
            continue
        entradas.append({
            'aba': nome_aba,
            'nome_empreendimento': info['nome_empreendimento'],
            'incorporador_nome': info['incorporador_nome'],
            'texto': '\n'.join(linhas),
        })
    return entradas

def localizar_nbr_do_empreendimento(empreendimento, entradas_nbr):
    """Retorna as entradas NBR que pertencem ao empreendimento da planilha oficial.
    Compara a razão social da planilha com o incorporador_nome da aba NBR e também
    com o nome comercial (relação de prefixo), na mesma regra usada para os Contratos PJ.
    Pode retornar mais de uma entrada (ex.: VIC NOVA IGUAÇU tem Viena Lírio e Viena
    Violeta) — nesse caso todas são anexadas e a IA escolhe pela Cláusula D do contrato."""
    emp_norm = normalizar_para_comparacao(empreendimento)
    if not emp_norm:
        return []
    encontradas = []
    for entrada in entradas_nbr:
        for candidato in (entrada['incorporador_nome'], entrada['nome_empreendimento'], entrada['aba']):
            cand_norm = normalizar_para_comparacao(candidato)
            if cand_norm and (emp_norm.startswith(cand_norm) or cand_norm.startswith(emp_norm)):
                encontradas.append(entrada)
                break
    return encontradas
