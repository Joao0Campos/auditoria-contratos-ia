import os
import time
import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from config import (
    PLANILHA_ARQUIVO,
    COR_VIC_LARANJA_MEDIO,
    COR_VIC_LARANJA_ESCURO,
    COR_VIC_AMARELO,
    COR_VIC_VERDE,
    COR_VIC_CINZA_CLARO,
    COR_VIC_TEXTO_ESCURO,
    LARGURAS_COLUNA,
    LARGURA_COLUNA_PADRAO
)
from utils.formatters import remover_acentos

def verificar_planilha_gravavel(caminho, max_tentativas=6, espera=10):
    """Confirma que a planilha pode ser aberta para escrita ANTES de começar o lote.
    Evita rodar (e gastar cota de API) um lote inteiro sem conseguir salvar o resultado
    porque o Excel estava aberto desde o início."""
    if not os.path.exists(caminho):
        print(f"[ERRO] Arquivo não encontrado: {caminho}")
        return False
    for tentativa in range(1, max_tentativas + 1):
        try:
            with open(caminho, 'a+b'):
                pass
            return True
        except PermissionError:
            if tentativa < max_tentativas:
                print(
                    f"\n{'!' * 60}\n"
                    f"[AVISO] O arquivo '{os.path.basename(caminho)}' está aberto/bloqueado.\n"
                    f"FECHE O EXCEL AGORA antes de continuar.\n"
                    f"Verificando de novo em {espera}s (tentativa {tentativa}/{max_tentativas})...\n"
                    f"{'!' * 60}\n"
                )
                time.sleep(espera)
    return False

def aplicar_visual_vic(worksheet):
    """Aplica o visual padrão VIC (cabeçalho laranja, zebra nas linhas de dados,
    semáforo na coluna Gravidade quando ela existir, largura de coluna, cabeçalho
    congelado e auto-filtro) numa aba já escrita pelo pandas. Reaproveitado pelas
    três abas do Excel de saída (Base, Auditoria_CEF, Divergencias)."""
    cabecalhos = [c.value for c in worksheet[1]]

    formato_quebra = Alignment(wrapText=True, vertical='top')
    for col in worksheet.columns:
        for cell in col:
            cell.alignment = formato_quebra

    # Cabeçalho com a cor institucional da VIC (laranja)
    preenchimento_header = PatternFill(start_color=COR_VIC_LARANJA_MEDIO, end_color=COR_VIC_LARANJA_MEDIO, fill_type='solid')
    fonte_header = Font(color="FFFFFFFF", bold=True)
    for cell in worksheet[1]:
        cell.fill = preenchimento_header
        cell.font = fonte_header
        cell.alignment = Alignment(wrapText=True, vertical='center', horizontal='center')

    col_gravidade = cabecalhos.index('Gravidade') + 1 if 'Gravidade' in cabecalhos else None

    # Zebra nas linhas de dados (a coluna Gravidade fica de fora, pois tem cor própria)
    preenchimento_zebra = PatternFill(start_color=COR_VIC_CINZA_CLARO, end_color=COR_VIC_CINZA_CLARO, fill_type='solid')
    for linha in range(2, worksheet.max_row + 1):
        if linha % 2 == 1:
            for col_idx in range(1, len(cabecalhos) + 1):
                if col_idx == col_gravidade:
                    continue
                worksheet.cell(row=linha, column=col_idx).fill = preenchimento_zebra

    # Destaque de cor (semáforo) na coluna Gravidade, seguindo a paleta da VIC.
    if col_gravidade:
        preenchimento_critico = PatternFill(start_color=COR_VIC_LARANJA_ESCURO, end_color=COR_VIC_LARANJA_ESCURO, fill_type='solid')
        preenchimento_moderado = PatternFill(start_color=COR_VIC_AMARELO, end_color=COR_VIC_AMARELO, fill_type='solid')
        preenchimento_ok = PatternFill(start_color=COR_VIC_VERDE, end_color=COR_VIC_VERDE, fill_type='solid')
        fonte_clara = Font(color="FFFFFFFF", bold=True)
        fonte_escura = Font(color=COR_VIC_TEXTO_ESCURO, bold=True)

        for linha in range(2, worksheet.max_row + 1):
            cel_grav = worksheet.cell(row=linha, column=col_gravidade)
            valor_norm = remover_acentos(str(cel_grav.value or '')).strip().upper()
            cel_grav.alignment = Alignment(wrapText=True, vertical='center', horizontal='center')
            if valor_norm == 'CRITICO':
                cel_grav.fill = preenchimento_critico
                cel_grav.font = fonte_clara
            elif valor_norm == 'MODERADO':
                cel_grav.fill = preenchimento_moderado
                cel_grav.font = fonte_escura
            elif valor_norm in ('N/A', 'OK'):
                cel_grav.fill = preenchimento_ok
                cel_grav.font = fonte_clara

    # Largura de colunas legível + cabeçalho fixo + filtro
    for indice, nome_coluna in enumerate(cabecalhos, start=1):
        largura = LARGURAS_COLUNA.get(nome_coluna, LARGURA_COLUNA_PADRAO)
        worksheet.column_dimensions[get_column_letter(indice)].width = largura

    worksheet.freeze_panes = 'A2'
    worksheet.auto_filter.ref = worksheet.dimensions
    worksheet.row_dimensions[1].height = 32

def montar_df_divergencias(df, divergencias_por_linha):
    """Uma linha POR DIVERGÊNCIA (não por contrato), sem células mescladas — as
    colunas de identificação repetem em cada linha de divergência do mesmo
    contrato, pra não quebrar filtro/tabela dinâmica."""
    colunas_divergencias = ['NUM_VENDA', 'NOME', 'CGCCFO', 'Empreendimento', 'Campo', 'Consta', 'Deveria_ser', 'Documento', 'Gravidade']
    linhas = []
    for indice_linha, divergencias in divergencias_por_linha.items():
        linha_origem = df.loc[indice_linha]
        for div in divergencias:
            linhas.append({
                'NUM_VENDA': linha_origem.get('NUM_VENDA', ''),
                'NOME': linha_origem.get('NOME', ''),
                'CGCCFO': linha_origem.get('CGCCFO', ''),
                'Empreendimento': linha_origem.get('Empreendimento', ''),
                'Campo': div['campo'],
                'Consta': div['valor_encontrado'],
                'Deveria_ser': div['valor_esperado'],
                'Documento': div['documento_origem'],
                'Gravidade': div['gravidade'],
            })
    return pd.DataFrame(linhas, columns=colunas_divergencias)

def salvar_excel_uma_vez(df, colunas_originais, divergencias_por_linha, caminho_planilha=PLANILHA_ARQUIVO):
    """Escreve num arquivo temporário e só troca pelo real no final (os.replace é atômico).
    Evita corrupção caso ocorra interrupção no meio da gravação."""
    raiz_planilha, extensao_planilha = os.path.splitext(caminho_planilha)
    caminho_temporario = f"{raiz_planilha}.tmp{os.getpid()}{extensao_planilha}"
    with pd.ExcelWriter(caminho_temporario, engine='openpyxl') as writer:
        # Aba 1: retrato bruto da entrada, só com as colunas originais
        df[colunas_originais].to_excel(writer, index=False, sheet_name='Base')
        aplicar_visual_vic(writer.sheets['Base'])

        # Aba 2: uma linha por contrato, com todas as colunas de auditoria
        df.to_excel(writer, index=False, sheet_name='Auditoria_CEF')
        aplicar_visual_vic(writer.sheets['Auditoria_CEF'])

        # Aba 3: uma linha por divergência (só contratos com divergência real)
        montar_df_divergencias(df, divergencias_por_linha).to_excel(writer, index=False, sheet_name='Divergencias')
        aplicar_visual_vic(writer.sheets['Divergencias'])

    os.replace(caminho_temporario, caminho_planilha)

def salvar_excel_com_retentativa(df, colunas_originais, divergencias_por_linha, caminho_planilha=PLANILHA_ARQUIVO):
    """Tenta salvar a planilha com retentativas caso esteja aberta pelo usuário."""
    max_tentativas_save = 6
    espera_entre_tentativas = 10

    for tentativa_save in range(1, max_tentativas_save + 1):
        try:
            salvar_excel_uma_vez(df, colunas_originais, divergencias_por_linha, caminho_planilha)
            print("✓ Excel atualizado (abas Base, Auditoria_CEF e Divergencias).")
            return
        except PermissionError:
            if tentativa_save < max_tentativas_save:
                print(
                    f"\n{'!' * 60}\n"
                    f"[AVISO] O Excel parece estar aberto e bloqueou o salvamento.\n"
                    f"FECHE O ARQUIVO '{os.path.basename(caminho_planilha)}' AGORA.\n"
                    f"Tentando de novo em {espera_entre_tentativas}s "
                    f"(tentativa {tentativa_save}/{max_tentativas_save})...\n"
                    f"{'!' * 60}\n"
                )
                time.sleep(espera_entre_tentativas)
            else:
                print(
                    f"\n{'!' * 60}\n"
                    f"[ERRO CRÍTICO] Não foi possível salvar o Excel após {max_tentativas_save} tentativas.\n"
                    f"O ARQUIVO PROVAVELMENTE CONTINUA ABERTO. Os resultados deste lote "
                    f"NÃO foram persistidos em disco (mas continuam em memória e serão "
                    f"tentados no próximo checkpoint).\n"
                    f"{'!' * 60}\n"
                )
        except Exception as e:
            print(f"[ERRO] Não foi possível salvar o Excel: {e}")
            return
