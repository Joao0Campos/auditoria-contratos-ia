import os
import re
import time
import threading
import concurrent.futures
import pandas as pd
from pydantic import ValidationError

from google import genai
from google.genai import types, errors

from config import (
    MINHA_CHAVE,
    PLANILHA_ARQUIVO,
    PASTA_CLIENTES,
    PASTA_PJ,
    PASTA_MATRICULAS,
    PLANILHA_NBR,
    PROMPT_TEMPLATE_PATH,
    MODEL_NAME,
    DELAY_FREE_TIER,
    MAX_WORKERS,
    SALVAR_A_CADA,
    LIMITE_FALHAS_SEGUIDAS,
    VERBOSE
)
from models import ResultadoAuditoria
from utils.formatters import (
    remover_acentos,
    normalizar_codigo_venda,
    eh_divergencia_real
)
from ui.config_window import abrir_tela_configuracao
from services.pdf_service import localizar_arquivos_pj
from services.nbr_service import (
    carregar_nbr_consolidado,
    localizar_nbr_do_empreendimento
)
from services.excel_service import (
    verificar_planilha_gravavel,
    salvar_excel_com_retentativa
)

class AuditRunner:
    def __init__ (self):
        self.client = None
        self.prompt_template = ""
        self.entradas_nbr = []
        self.df = None
        self.colunas_novas = ['Status_Auditoria', 'Gravidade', 'Motivo_Divergencia', 'Processado', 'Matricula_Anexada', 'NBR_Utilizada']
        self.colunas_originais = []

        self.pasta_clientes = PASTA_CLIENTES
        self.pasta_pj = PASTA_PJ
        self.pasta_matriculas = PASTA_MATRICULAS
        self.empreendimentos_selecionados = []
        self.emp_normalizados = None

        self.codigo_para_indice = {}
        self.codigos_ordenados = []
        self.codigo_para_indice_completo = {}
        self.codigos_ordenados_completo = []

        self.arquivos_pj_nuvem = {}
        self.cache_arquivos_pj = {}
        self.arquivos_matriculas_cache = []

        self.divergencias_por_linha = {}
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_tokens = 0

        self.contador_nao_salvos = {'total': 0}
        self.contador_falhas_seguidas = {'total': 0}
        self.interromper_lote = threading.Event()

        self.pj_lock = threading.Lock()
        self.state_lock = threading.Lock()

    def log_detalhe(self, msg):
        if VERBOSE:
            print(msg)

    def localizar_codigo_no_nome(self, nome_arquivo):
        for cod in self.codigos_ordenados:
            if re.search(rf'(?<!\d){re.escape(cod)}(?!\d)', nome_arquivo):
                return cod
        return None

    def localizar_codigo_no_nome_completo(self, nome_arquivo):
        for cod in self.codigos_ordenados_completo:
            if re.search(rf'(?<!\d){re.escape(cod)}(?!\d)', nome_arquivo):
                return cod
        return None

    def obter_arquivos_pj(self, nome_pj_limpo):
        if nome_pj_limpo not in self.cache_arquivos_pj:
            self.cache_arquivos_pj[nome_pj_limpo] = localizar_arquivos_pj(nome_pj_limpo, self.pasta_pj)
        return self.cache_arquivos_pj[nome_pj_limpo]

    def salvar_excel(self):
        salvar_excel_com_retentativa(self.df, self.colunas_originais, self.divergencias_por_linha, PLANILHA_ARQUIVO)

    def _registrar_sucesso(self):
        with self.state_lock:
            self.contador_falhas_seguidas['total'] = 0

    def _registrar_falha_e_checar_parada(self, nome_arquivo):
        with self.state_lock:
            self.contador_falhas_seguidas['total'] += 1
            atingiu_limite = self.contador_falhas_seguidas['total'] >= LIMITE_FALHAS_SEGUIDAS
            if atingiu_limite and not self.interromper_lote.is_set():
                self.interromper_lote.set()
                print(
                    f"\n{'!' * 60}\n"
                    f"[PARADA AUTOMÁTICA] {LIMITE_FALHAS_SEGUIDAS} contratos seguidos falharam sem "
                    f"nenhum sucesso no meio (último: {nome_arquivo}).\n"
                    f"Provável causa: saldo da chave esgotado ou problema persistente na API.\n"
                    f"Interrompendo o restante do lote pra não desperdiçar tempo — os contratos "
                    f"ainda não tentados continuam marcados como pendentes (Processado='NÃO').\n"
                    f"Resolva o problema (ex.: recarregue o saldo) e rode o script de novo pra continuar de onde parou.\n"
                    f"{'!' * 60}\n"
                )

    def processar_contrato(self, nome_arquivo):
        if self.interromper_lote.is_set():
            return 'lote_interrompido'

        caminho_arquivo_cef = os.path.join(self.pasta_clientes, nome_arquivo)

        codigo_venda = self.localizar_codigo_no_nome(nome_arquivo)
        if codigo_venda is None:
            if self.emp_normalizados is not None and self.localizar_codigo_no_nome_completo(nome_arquivo) is not None:
                print(f"[FILTRO] Fora do empreendimento selecionado, ignorado: {nome_arquivo}")
                return 'fora_do_filtro'
            print(f"[AVISO] Arquivo ignorado (Código não está na planilha): {nome_arquivo}")
            return 'nao_encontrado'

        indice_linha = self.codigo_para_indice[codigo_venda]

        with self.state_lock:
            linha_cliente = self.df.loc[indice_linha].copy()
            if str(linha_cliente.get('Processado', '')).strip().upper() == 'SIM':
                return 'ja_processado'

        # Trava de segurança contra colisão de código
        nome_esperado_norm = remover_acentos(str(linha_cliente['NOME'])).upper()
        nome_arquivo_norm = remover_acentos(nome_arquivo).upper()
        tokens_nome = [t for t in re.split(r'\s+', nome_esperado_norm) if len(t) > 2]
        tokens_batem = sum(1 for t in tokens_nome if t in nome_arquivo_norm)
        if tokens_nome and (tokens_batem / len(tokens_nome)) < 0.5:
            print(
                f"[AVISO] {nome_arquivo}: o código de venda {codigo_venda} bate com a linha de "
                f"\"{linha_cliente['NOME']}\", mas o nome não confere no arquivo — pulando para não "
                f"cruzar dados de clientes diferentes. Verifique manualmente este arquivo."
            )
            return 'nome_nao_confere'

        try:
            self._processar_contrato_interno(nome_arquivo, caminho_arquivo_cef, indice_linha, linha_cliente, codigo_venda)
            return 'processado'
        except Exception as e:
            print(f"\n[ERRO INESPERADO] Falha ao processar {nome_arquivo}: {e}")
            with self.state_lock:
                self.df.at[indice_linha, 'Status_Auditoria'] = "ERRO INTERNO"
                self.df.at[indice_linha, 'Gravidade'] = "N/A"
                self.df.at[indice_linha, 'Motivo_Divergencia'] = "Falha temporária ao processar — será reprocessado automaticamente."
                self.df.at[indice_linha, 'Processado'] = 'NÃO'
            self.salvar_excel()
            self._registrar_falha_e_checar_parada(nome_arquivo)
            return 'erro'

    def _processar_contrato_interno(self, nome_arquivo, caminho_arquivo_cef, indice_linha, linha_cliente, codigo_venda):
        nome_cliente = str(linha_cliente['NOME']).strip()
        empreendimento = str(linha_cliente['Empreendimento']).strip()
        cpf = str(linha_cliente['CGCCFO']).strip()
        rg = str(linha_cliente['CIDENTIDADE']).strip()

        endereco_raw = linha_cliente.get('ENDERECO', '')
        if pd.isna(endereco_raw) or str(endereco_raw).strip().lower() in ['nan', 'nat', 'none', '']:
            endereco = "NÃO INFORMADO (IGNORAR VALIDAÇÃO)"
        else:
            endereco = str(endereco_raw).strip()

        cnh_raw = linha_cliente.get('CNH', '')
        if pd.isna(cnh_raw) or str(cnh_raw).strip().lower() in ['nan', 'nat', 'none', '']:
            cnh = "NÃO INFORMADO (IGNORAR VALIDAÇÃO)"
        else:
            cnh = str(cnh_raw).strip()

        self.log_detalhe(f"\n====================================================")
        self.log_detalhe(f"[{nome_arquivo}] Vínculo Encontrado -> Cliente: {nome_cliente} | Emp: {empreendimento}")
        self.log_detalhe(f"====================================================")

        arquivos_para_analise = []
        arquivos_para_deletar = []

        # --- A. LÓGICA DO CONTRATO PJ ---
        nome_pj_limpo = remover_acentos(empreendimento)
        with self.pj_lock:
            arquivos_pj_emp = self.obter_arquivos_pj(nome_pj_limpo)
            if not arquivos_pj_emp:
                print(f"[ALERTA] Nenhum Contrato PJ encontrado para {empreendimento} na pasta {self.pasta_pj}.")

        for nome_arquivo_pj in arquivos_pj_emp:
            chave_cache = remover_acentos(os.path.splitext(nome_arquivo_pj)[0])
            with self.pj_lock:
                doc_pj = self.arquivos_pj_nuvem.get(chave_cache)
            if doc_pj is None:
                caminho_pj = os.path.join(self.pasta_pj, nome_arquivo_pj)
                self.log_detalhe(f"[{nome_arquivo}] -> Fazendo upload do Contrato PJ: {nome_arquivo_pj}...")
                doc_pj = self.client.files.upload(
                    file=caminho_pj,
                    config={'display_name': chave_cache}
                )
                with self.pj_lock:
                    doc_pj = self.arquivos_pj_nuvem.setdefault(chave_cache, doc_pj)
            arquivos_para_analise.append(doc_pj)

        if len(arquivos_pj_emp) > 1:
            self.log_detalhe(f"[{nome_arquivo}] -> {len(arquivos_pj_emp)} Contratos PJ anexados (múltiplos Módulos) — a IA identifica o Módulo correto pela Cláusula D.")

        # --- B. UPLOAD DO CONTRATO CEF ---
        self.log_detalhe(f"[{nome_arquivo}] -> Enviando Contrato CEF para a Inteligência...")
        try:
            with open(caminho_arquivo_cef, 'rb') as arquivo_cef_bin:
                doc_cef = self.client.files.upload(
                    file=arquivo_cef_bin,
                    config={
                        'display_name': remover_acentos(nome_arquivo),
                        'mime_type': 'application/pdf',
                    }
                )
            arquivos_para_analise.append(doc_cef)
            arquivos_para_deletar.append(doc_cef)
        except Exception as e:
            print(f"[ERRO] Falha ao subir o arquivo {nome_arquivo}: {e}")
            with self.state_lock:
                self.df.at[indice_linha, 'Status_Auditoria'] = "ERRO INTERNO"
                self.df.at[indice_linha, 'Gravidade'] = "N/A"
                self.df.at[indice_linha, 'Motivo_Divergencia'] = "Falha temporária ao enviar o Contrato CEF — será reprocessado automaticamente."
                self.df.at[indice_linha, 'Processado'] = 'NÃO'
            self.salvar_excel()
            self._registrar_falha_e_checar_parada(nome_arquivo)
            return

        # --- C. LÓGICA DA MATRÍCULA ---
        contrato_matricula_encontrado = False
        nome_cliente_busca = remover_acentos(nome_cliente).upper()
        tokens_nome_cliente = [t for t in re.split(r'\s+', nome_cliente_busca) if len(t) > 2]

        if self.arquivos_matriculas_cache:
            for nome_arquivo_mat in self.arquivos_matriculas_cache:
                nome_arquivo_mat_limpo = remover_acentos(nome_arquivo_mat).upper()

                if tokens_nome_cliente and all(t in nome_arquivo_mat_limpo for t in tokens_nome_cliente):
                    self.log_detalhe(f"[{nome_arquivo}] -> Matrícula Individualizada localizada! Anexando: {nome_arquivo_mat}...")
                    caminho_matricula = os.path.join(self.pasta_matriculas, nome_arquivo_mat)
                    try:
                        with open(caminho_matricula, 'rb') as arquivo_matricula_bin:
                            doc_matricula = self.client.files.upload(
                                file=arquivo_matricula_bin,
                                config={
                                    'display_name': remover_acentos(nome_arquivo_mat),
                                    'mime_type': 'application/pdf',
                                }
                            )
                        arquivos_para_analise.append(doc_matricula)
                        arquivos_para_deletar.append(doc_matricula)
                        contrato_matricula_encontrado = True
                        break
                    except Exception as e:
                        print(f"[ERRO] Falha ao subir a matrícula {nome_arquivo_mat}: {e}")

        if not contrato_matricula_encontrado:
            self.log_detalhe(f"[{nome_arquivo}] -> Nenhuma matrícula individual anexada (Auditoria seguirá as regras gerais).")

        # --- C2. DADOS NBR 12.721 ---
        dados_nbr = "INDISPONÍVEL — não aplique o PASSO 3B."
        nbr_utilizada = False
        if not contrato_matricula_encontrado and self.entradas_nbr:
            nbr_do_emp = localizar_nbr_do_empreendimento(empreendimento, self.entradas_nbr)
            if nbr_do_emp:
                dados_nbr = "\n\n".join(
                    f"### NBR do empreendimento: {entrada['nome_empreendimento'] or entrada['aba']}\n{entrada['texto']}"
                    for entrada in nbr_do_emp
                )
                nbr_utilizada = True
                self.log_detalhe(f"[{nome_arquivo}] -> Sem matrícula: quadro NBR de {len(nbr_do_emp)} empreendimento(s) anexado ao prompt para validar áreas/vaga.")

        # --- D. PROMPT DINÂMICO INJETADO ---
        prompt_auditoria = self.prompt_template.format(
            nome_cliente=nome_cliente,
            cpf=cpf,
            rg=rg,
            cnh=cnh,
            endereco=endereco,
            empreendimento=empreendimento,
            codigo_venda=codigo_venda,
            dados_nbr=dados_nbr,
        )

        conteudo_completo = arquivos_para_analise + [prompt_auditoria]
        max_tentativas = 5
        self.log_detalhe(f"[{nome_arquivo}] Auditoria em andamento...")

        status_atual = "ERRO INTERNO"
        motivo_atual = "Falha na análise"
        gravidade_atual = "-"
        divergencias_reais = []
        esgotou_por_rate_limit = False

        # --- E. EXECUÇÃO DA IA (SAÍDA ESTRUTURADA + RETENTATIVAS) ---
        for tentativa in range(1, max_tentativas + 1):
            try:
                resposta = self.client.models.generate_content(
                    model=MODEL_NAME,
                    contents=conteudo_completo,
                    config=types.GenerateContentConfig(
                        temperature=0.0,
                        response_mime_type='application/json',
                        response_schema=ResultadoAuditoria,
                    )
                )

                resultado = resposta.parsed
                if resultado is None:
                    resultado = ResultadoAuditoria.model_validate_json(resposta.text)

                divergencias_reais = [d for d in resultado.divergencias if eh_divergencia_real(d)]

                status_atual = "DIVERGÊNCIA" if divergencias_reais else "OK"

                if status_atual == "DIVERGÊNCIA":
                    tem_erro_critico = any(d.gravidade == "CRITICO" for d in divergencias_reais)
                    tem_erro_moderado = any(d.gravidade == "MODERADO" for d in divergencias_reais)
                    if tem_erro_critico:
                        gravidade_atual = "CRÍTICO"
                    elif tem_erro_moderado:
                        gravidade_atual = "MODERADO"
                    else:
                        gravidade_atual = "NÃO CLASSIFICADO"

                    motivo_atual = "\n".join(
                        f'- [{d.gravidade}] | {d.campo} | Consta "{d.valor_encontrado}" no {d.documento_origem} | '
                        f'Deveria ser "{d.valor_esperado}" conforme Planilha Oficial.'
                        for d in divergencias_reais
                    )
                else:
                    gravidade_atual = "N/A"
                    motivo_atual = "Documentação em conformidade"

                try:
                    usage = resposta.usage_metadata
                    with self.state_lock:
                        self.total_input_tokens += usage.prompt_token_count
                        self.total_output_tokens += usage.candidates_token_count
                        self.total_tokens += usage.total_token_count
                except Exception:
                    pass

                print(f"[{nome_arquivo}] -> Concluído! Resultado: {status_atual} | Gravidade: {gravidade_atual}")
                break

            except errors.APIError as e:
                if "503" in str(e) or "UNAVAILABLE" in str(e) or "429" in str(e):
                    print(f"\n[{nome_arquivo}] [TENTATIVA {tentativa}/{max_tentativas}] Servidor ocupado ou Rate Limit.")
                    esgotou_por_rate_limit = True
                    time.sleep(15 * tentativa)
                else:
                    print(f"\n[ERRO DA API] {nome_arquivo}: {e}")
                    motivo_atual = "Falha na API ao analisar — será reprocessado automaticamente."
                    break
            except (ValidationError, ValueError) as e:
                print(f"\n[{nome_arquivo}] [TENTATIVA {tentativa}/{max_tentativas}] Resposta fora do schema esperado: {e}")
                esgotou_por_rate_limit = False
                time.sleep(5)
            except Exception as e:
                print(f"\n[ERRO FATAL NO MODELO] {nome_arquivo}: {e}")
                motivo_atual = "Falha inesperada ao analisar — será reprocessado automaticamente."
                break
        else:
            if esgotou_por_rate_limit:
                motivo_atual = (
                    "Falha na API após múltiplas tentativas (servidor ocupado/rate limit) — "
                    "será reprocessado automaticamente."
                )

        # --- F. CHECKPOINT NA PLANILHA ---
        with self.state_lock:
            self.df.at[indice_linha, 'Status_Auditoria'] = status_atual
            self.df.at[indice_linha, 'Gravidade'] = gravidade_atual
            self.df.at[indice_linha, 'Motivo_Divergencia'] = motivo_atual
            self.df.at[indice_linha, 'Processado'] = 'NÃO' if status_atual == "ERRO INTERNO" else 'SIM'
            self.df.at[indice_linha, 'Matricula_Anexada'] = 'SIM' if contrato_matricula_encontrado else 'NÃO'
            self.df.at[indice_linha, 'NBR_Utilizada'] = 'SIM' if nbr_utilizada else 'NÃO'

            if divergencias_reais:
                self.divergencias_por_linha[indice_linha] = [
                    {
                        'campo': d.campo,
                        'valor_encontrado': d.valor_encontrado,
                        'valor_esperado': d.valor_esperado,
                        'documento_origem': d.documento_origem,
                        'gravidade': d.gravidade,
                    }
                    for d in divergencias_reais
                ]
            else:
                self.divergencias_por_linha.pop(indice_linha, None)

            self.contador_nao_salvos['total'] += 1
            if self.contador_nao_salvos['total'] >= SALVAR_A_CADA:
                self.salvar_excel()
                self.contador_nao_salvos['total'] = 0

        if status_atual == "ERRO INTERNO":
            self._registrar_falha_e_checar_parada(nome_arquivo)
        else:
            self._registrar_sucesso()

        # --- G. LIMPEZA DOS ARQUIVOS ---
        self.log_detalhe(f"[{nome_arquivo}] Limpando memória da IA...")
        for doc in arquivos_para_deletar:
            try:
                self.client.files.delete(name=doc.name)
            except Exception:
                pass

        if DELAY_FREE_TIER:
            time.sleep(DELAY_FREE_TIER)

    def run(self):
        print("Iniciando Motor de Auditoria Preditiva V2 (Lógica Reversa + Matrículas)...")

        if not MINHA_CHAVE:
            print(
                "\n[ERRO CRÍTICO] Variável de ambiente GEMINI_API_KEY não definida.\n"
                "Defina-a no terminal ou crie um arquivo .env a partir de .env.example."
            )
            return

        if not verificar_planilha_gravavel(PLANILHA_ARQUIVO):
            print(
                f"\n{'!' * 60}\n"
                f"[ERRO CRÍTICO] '{os.path.basename(PLANILHA_ARQUIVO)}' continua bloqueado.\n"
                f"Feche o Excel e rode o script novamente. Nenhum contrato foi processado ainda "
                f"(nenhuma cota de API foi gasta).\n"
                f"{'!' * 60}\n"
            )
            return

        with open(PROMPT_TEMPLATE_PATH, "r", encoding="utf-8") as f:
            self.prompt_template = f.read()

        self.client = genai.Client(api_key=MINHA_CHAVE)

        self.entradas_nbr = carregar_nbr_consolidado(PLANILHA_NBR)
        if self.entradas_nbr:
            nomes_nbr = ", ".join(e['nome_empreendimento'] or e['aba'] for e in self.entradas_nbr)
            print(f"Consolidado NBR carregado: {len(self.entradas_nbr)} empreendimento(s) ({nomes_nbr}).")

        try:
            self.df = pd.read_excel(PLANILHA_ARQUIVO, sheet_name='Auditoria_CEF')
        except ValueError:
            self.df = pd.read_excel(PLANILHA_ARQUIVO)

        for col in self.colunas_novas:
            if col not in self.df.columns:
                self.df[col] = None
            self.df[col] = self.df[col].astype('object')

        self.colunas_originais = [c for c in self.df.columns if c not in self.colunas_novas]

        empreendimentos_disponiveis = sorted(
            self.df['Empreendimento'].dropna().astype(str).str.strip().replace('', pd.NA).dropna().unique()
        )
        config_execucao = abrir_tela_configuracao(
            empreendimentos_disponiveis, PASTA_CLIENTES, PASTA_PJ, PASTA_MATRICULAS
        )
        if not config_execucao['confirmado']:
            print("Auditoria cancelada — janela de configuração fechada sem confirmar.")
            return

        self.pasta_clientes = config_execucao['pasta_clientes']
        self.pasta_pj = config_execucao['pasta_pj']
        self.pasta_matriculas = config_execucao['pasta_matriculas']
        print(f"Pastas em uso -> Contratos: {self.pasta_clientes} | PJ: {self.pasta_pj} | Matrículas: {self.pasta_matriculas}")

        self.empreendimentos_selecionados = config_execucao['empreendimentos']
        if self.empreendimentos_selecionados:
            print(f"Filtro ativo -> processando apenas: {', '.join(self.empreendimentos_selecionados)}")
            self.emp_normalizados = {remover_acentos(e).upper() for e in self.empreendimentos_selecionados}
        else:
            print("Nenhum empreendimento marcado -> processando todos.")
            self.emp_normalizados = None

        for idx, valor in self.df['NUM_VENDA'].items():
            if self.emp_normalizados is not None:
                emp_linha = remover_acentos(str(self.df.at[idx, 'Empreendimento']).strip()).upper()
                if emp_linha not in self.emp_normalizados:
                    continue

            cod = normalizar_codigo_venda(valor)
            if not cod or cod.lower() == 'nan':
                continue
            if cod in self.codigo_para_indice:
                print(f"[AVISO] Código de venda duplicado na planilha: {cod} (mantendo a primeira ocorrência, linha {self.codigo_para_indice[cod]}).")
                continue
            self.codigo_para_indice[cod] = idx
        self.codigos_ordenados = sorted(self.codigo_para_indice.keys(), key=len, reverse=True)

        if self.emp_normalizados is not None:
            self.codigo_para_indice_completo = {}
            for idx, valor in self.df['NUM_VENDA'].items():
                cod = normalizar_codigo_venda(valor)
                if not cod or cod.lower() == 'nan':
                    continue
                if cod not in self.codigo_para_indice_completo:
                    self.codigo_para_indice_completo[cod] = idx
            self.codigos_ordenados_completo = sorted(self.codigo_para_indice_completo.keys(), key=len, reverse=True)
        else:
            self.codigo_para_indice_completo = self.codigo_para_indice
            self.codigos_ordenados_completo = self.codigos_ordenados

        print("Verificando Contratos PJ na nuvem...")
        try:
            for f in self.client.files.list():
                self.arquivos_pj_nuvem[f.display_name] = f
        except Exception as e:
            print(f"[AVISO] Não foi possível listar arquivos da nuvem. Detalhe: {e}")

        empreendimentos_para_pj = self.empreendimentos_selecionados or empreendimentos_disponiveis
        print(f"Preparando Contratos PJ de {len(empreendimentos_para_pj)} empreendimento(s)...")
        for nome_emp in empreendimentos_para_pj:
            nome_pj_limpo = remover_acentos(nome_emp)
            arquivos_pj_emp = self.obter_arquivos_pj(nome_pj_limpo)
            if not arquivos_pj_emp:
                print(f"[ALERTA] Nenhum Contrato PJ encontrado para {nome_emp} na pasta {self.pasta_pj}.")
                continue
            for nome_arquivo_pj in arquivos_pj_emp:
                chave_cache = remover_acentos(os.path.splitext(nome_arquivo_pj)[0])
                if chave_cache in self.arquivos_pj_nuvem:
                    continue
                caminho_pj = os.path.join(self.pasta_pj, nome_arquivo_pj)
                print(f"-> Fazendo upload do Contrato PJ: {nome_arquivo_pj}...")
                try:
                    doc_pj = self.client.files.upload(file=caminho_pj, config={'display_name': chave_cache})
                    self.arquivos_pj_nuvem[chave_cache] = doc_pj
                except Exception as e:
                    print(f"[ERRO] Falha ao subir o Contrato PJ {nome_arquivo_pj}: {e}")

        if os.path.exists(self.pasta_matriculas):
            self.arquivos_matriculas_cache = [f for f in os.listdir(self.pasta_matriculas) if f.lower().endswith('.pdf')]
        else:
            self.arquivos_matriculas_cache = []

        try:
            df_divergencias_existente = pd.read_excel(PLANILHA_ARQUIVO, sheet_name='Divergencias')
        except ValueError:
            df_divergencias_existente = pd.DataFrame()

        for _, linha_div in df_divergencias_existente.iterrows():
            cod_div = normalizar_codigo_venda(linha_div.get('NUM_VENDA', ''))
            idx_div = self.codigo_para_indice_completo.get(cod_div)
            if idx_div is None:
                continue
            self.divergencias_por_linha.setdefault(idx_div, []).append({
                'campo': linha_div.get('Campo', ''),
                'valor_encontrado': linha_div.get('Consta', ''),
                'valor_esperado': linha_div.get('Deveria_ser', ''),
                'documento_origem': linha_div.get('Documento', ''),
                'gravidade': linha_div.get('Gravidade', ''),
            })

        print(f"\nLendo contratos na pasta '{self.pasta_clientes}'...")
        arquivos_pdf = [f for f in os.listdir(self.pasta_clientes) if f.lower().endswith('.pdf')]
        total_arquivos = len(arquivos_pdf)
        concluidos = 0

        contadores_status = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(self.processar_contrato, nome): nome for nome in arquivos_pdf}
            for future in concurrent.futures.as_completed(futures):
                concluidos += 1
                try:
                    status_resultado = future.result() or 'desconhecido'
                except Exception as e:
                    print(f"\n[ERRO NÃO TRATADO] {futures[future]}: {e}")
                    status_resultado = 'erro'
                contadores_status[status_resultado] = contadores_status.get(status_resultado, 0) + 1
                resumo = ", ".join(f"{k}: {v}" for k, v in contadores_status.items())
                print(f"[PROGRESSO] {concluidos}/{total_arquivos} verificados ({resumo})")

        with self.state_lock:
            if self.contador_nao_salvos['total'] > 0:
                self.salvar_excel()
                self.contador_nao_salvos['total'] = 0

        print("\n============= RESUMO DA EXECUÇÃO =============")
        print("Processamento finalizado!")
        print(f"Total de arquivos na pasta       : {total_arquivos}")
        print(f"Processados de verdade (IA)      : {contadores_status.get('processado', 0)}")
        print(f"Já estavam processados antes     : {contadores_status.get('ja_processado', 0)}")
        print(f"Ignorados (fora do filtro)       : {contadores_status.get('fora_do_filtro', 0)}")
        print(f"Ignorados (código não encontrado): {contadores_status.get('nao_encontrado', 0)}")
        print(f"Ignorados (nome não confere)     : {contadores_status.get('nome_nao_confere', 0)}")
        print(f"Erros                            : {contadores_status.get('erro', 0)}")
        if contadores_status.get('lote_interrompido', 0):
            print(f"Não tentados (parada automática) : {contadores_status.get('lote_interrompido', 0)}")
            print(
                "\n[AVISO] O lote foi interrompido automaticamente por falhas seguidas — provável "
                "saldo esgotado. Resolva o problema e rode o script de novo: os contratos não "
                "tentados continuam pendentes e serão processados na próxima execução."
            )
        print(f"Total de tokens de entrada : {self.total_input_tokens:,}")
        print(f"Total de tokens de saída   : {self.total_output_tokens:,}")
        print(f"Total geral de tokens      : {self.total_tokens:,}")
        print("==============================================")
