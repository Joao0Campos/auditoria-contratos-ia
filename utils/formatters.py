import re
import unicodedata

def remover_acentos(texto):
    """Remove acentos, cedilhas e caracteres especiais de uma string."""
    try:
        texto_normalizado = unicodedata.normalize('NFKD', str(texto))
        texto_limpo = texto_normalizado.encode('ASCII', 'ignore').decode('ASCII')
        return texto_limpo
    except Exception:
        return texto

def normalizar_codigo_venda(valor):
    """Normaliza NUM_VENDA para string comparável (remove '.0' de floats do pandas)."""
    texto = str(valor).strip()
    if texto.endswith('.0'):
        texto = texto[:-2]
    return texto

def normalizar_para_comparacao(texto):
    """Remove acentos, caixa e qualquer caractere não alfanumérico. Usado para
    detectar divergências "falsas" que a IA às vezes reporta com valor_encontrado
    e valor_esperado na prática iguais (mesma regra de ignorar pontuação do prompt)."""
    sem_acento = remover_acentos(str(texto)).upper()
    return re.sub(r'[^A-Z0-9]', '', sem_acento)

def eh_divergencia_real(divergencia):
    """Trava de segurança final: filtra divergências que a IA às vezes aponta
    mesmo quando não deveria, sem depender só do prompt seguir a regra."""
    encontrado_norm = normalizar_para_comparacao(divergencia.valor_encontrado)
    esperado_norm = normalizar_para_comparacao(divergencia.valor_esperado)

    if encontrado_norm == esperado_norm:
        return False

    # Nome comercial/abreviado do empreendimento (ex.: "GRAN VIC BONSUCESSO", às vezes
    # com sufixo de módulo tipo "MODULO 1") vs. razão social completa da planilha
    # (ex.: "GRAN VIC BONSUCESSO EMPREENDIMENTOS IMOBILIARIOS SPE LTDA") não é
    # divergência — um é prefixo reconhecível do outro, ignorando o sufixo de módulo.
    if 'EMPREENDIMENTO' in normalizar_para_comparacao(divergencia.campo):
        encontrado_sem_modulo = re.sub(r'MODULO\d+$', '', encontrado_norm)
        esperado_sem_modulo = re.sub(r'MODULO\d+$', '', esperado_norm)
        if encontrado_sem_modulo and esperado_sem_modulo:
            if esperado_sem_modulo.startswith(encontrado_sem_modulo) or encontrado_sem_modulo.startswith(esperado_sem_modulo):
                return False

    return True
