import os
from utils.formatters import remover_acentos

def localizar_arquivos_pj(nome_pj_limpo, pasta_pj):
    """Retorna os nomes de arquivo (na pasta PJ) que pertencem ao empreendimento.
    Cobre o caso de existir mais de um Contrato de Abertura de Crédito por Módulo
    (ex.: "EMPREENDIMENTO.pdf", "EMPREENDIMENTO MODULO 1.pdf", "EMPREENDIMENTO MODULO 2.pdf")."""
    if not os.path.isdir(pasta_pj):
        return []
    prefixo = nome_pj_limpo.upper()
    encontrados = []
    for nome_arquivo in os.listdir(pasta_pj):
        if not nome_arquivo.lower().endswith('.pdf'):
            continue
        base = remover_acentos(os.path.splitext(nome_arquivo)[0]).upper()
        if base == prefixo or base.startswith((f"{prefixo} ", f"{prefixo}_", f"{prefixo}-")):
            encontrados.append(nome_arquivo)
    return sorted(encontrados)
