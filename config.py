import os

# ==========================================
# CONFIGURAÇÕES E CONSTANTES GLOBAIS
# ==========================================
CAMINHO_SCRIPT = os.path.dirname(os.path.abspath(__file__))

# Carrega um arquivo .env da raiz do projeto, se existir (opcional: requer python-dotenv).
# Variáveis já definidas no ambiente têm precedência sobre o .env.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(CAMINHO_SCRIPT, ".env"))
except ImportError:
    pass

# A chave NUNCA fica no código: vem da variável de ambiente GEMINI_API_KEY (ou do .env).
MINHA_CHAVE = os.environ.get("GEMINI_API_KEY", "").strip()

# Por padrão, os dados de entrada ficam na própria pasta do projeto (ignorados pelo .gitignore).
DIRETORIO_BASE = os.environ.get("AUDITORIA_DIR_BASE", CAMINHO_SCRIPT)
PLANILHA_ARQUIVO = os.path.join(DIRETORIO_BASE, "Sem_Registro.xlsx")
PASTA_CLIENTES = os.path.join(DIRETORIO_BASE, "CONTRATOS_GERAIS")
PASTA_PJ = os.path.join(DIRETORIO_BASE, "PJ_GERAIS")
PASTA_MATRICULAS = os.path.join(DIRETORIO_BASE, "MATRICULAS")
PLANILHA_NBR = os.path.join(DIRETORIO_BASE, "consolidado.xlsx")
PROMPT_TEMPLATE_PATH = os.path.join(CAMINHO_SCRIPT, "prompt_auditoria.txt")

# Configurações overridáveis via variável de ambiente
MODEL_NAME = os.environ.get("AUDITORIA_MODEL", "gemini-3.5-flash-lite")
DELAY_FREE_TIER = int(os.environ.get("AUDITORIA_DELAY", "15"))
MAX_WORKERS = int(os.environ.get("AUDITORIA_MAX_WORKERS", "1"))
SALVAR_A_CADA = max(1, int(os.environ.get("AUDITORIA_SALVAR_A_CADA", "15")))
LIMITE_FALHAS_SEGUIDAS = int(os.environ.get("AUDITORIA_LIMITE_FALHAS_SEGUIDAS", "8"))
VERBOSE = os.environ.get("AUDITORIA_VERBOSE", "0") == "1"

# Paleta de Cores Institucional VIC Engenharia
VIC_AZUL = "#009CAB"
VIC_LARANJA_MEDIO = "#F36F21"
VIC_LARANJA_ESCURO = "#EA582B"
VIC_AMARELO = "#F8B817"
VIC_VERDE = "#54BA49"
VIC_CINZA = "#ECECEC"
VIC_CINZA_CLARO = "#F7F7F7"
VIC_TEXTO_ESCURO = "#282828"
VIC_BRANCO = "#FFFFFF"

def _argb(hex_cor):
    return "FF" + hex_cor.lstrip("#").upper()

COR_VIC_AZUL = _argb(VIC_AZUL)
COR_VIC_LARANJA_MEDIO = _argb(VIC_LARANJA_MEDIO)
COR_VIC_LARANJA_ESCURO = _argb(VIC_LARANJA_ESCURO)
COR_VIC_AMARELO = _argb(VIC_AMARELO)
COR_VIC_VERDE = _argb(VIC_VERDE)
COR_VIC_CINZA = _argb(VIC_CINZA)
COR_VIC_CINZA_CLARO = _argb(VIC_CINZA_CLARO)
COR_VIC_TEXTO_ESCURO = _argb(VIC_TEXTO_ESCURO)

LARGURAS_COLUNA = {
    'Empreendimento': 34,
    'NOME': 28,
    'ENDERECO': 32,
    'Motivo_Divergencia': 70,
    'Status_Auditoria': 15,
    'Gravidade': 15,
    'Processado': 12,
    'Matricula_Anexada': 16,
    'NBR_Utilizada': 14,
    'NUM_VENDA': 14,
    'CGCCFO': 18,
    'Campo': 22,
    'Consta': 34,
    'Deveria_ser': 34,
    'Documento': 20,
}
LARGURA_COLUNA_PADRAO = 16
