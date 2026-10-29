import os

def abrir_tela_configuracao(opcoes_empreendimentos, pasta_clientes_padrao, pasta_pj_padrao, pasta_matriculas_padrao):
    """Abre a janela (pywebview) para escolher as pastas de origem e marcar os
    empreendimentos a auditar. MESMO retorno da versão antiga: dict com as pastas,
    a lista de empreendimentos marcados (vazia = todos) e 'confirmado'."""
    import webview  # pip install pywebview

    html_path = os.path.join(os.path.dirname(__file__), 'templates', 'config_window.html')
    with open(html_path, 'r', encoding='utf-8') as f:
        html_config = f.read()

    resultado = {
        'pasta_clientes': pasta_clientes_padrao,
        'pasta_pj': pasta_pj_padrao,
        'pasta_matriculas': pasta_matriculas_padrao,
        'empreendimentos': [],
        'confirmado': False,
    }

    class _Api:
        # PONTE 1: a tela pede pastas-padrão + a lista assim que o bridge fica pronto
        def carregar_dados(self):
            return {
                'pasta_clientes': resultado['pasta_clientes'],
                'pasta_pj': resultado['pasta_pj'],
                'pasta_matriculas': resultado['pasta_matriculas'],
                'empreendimentos': list(opcoes_empreendimentos),
            }

        # PONTE 2: abre o diálogo de pasta NATIVO do Windows e devolve o caminho absoluto
        def escolher_pasta(self, chave, atual):
            janela = webview.windows[0]
            selecao = janela.create_file_dialog(
                webview.FOLDER_DIALOG,
                directory=atual or os.path.expanduser("~"),
            )
            if selecao:
                resultado[chave] = selecao[0]
                return selecao[0]
            return None

        # PONTE 3: grava a config final e fecha a janela
        def confirmar(self, payload):
            resultado['pasta_clientes'] = payload.get('pasta_clientes', resultado['pasta_clientes'])
            resultado['pasta_pj'] = payload.get('pasta_pj', resultado['pasta_pj'])
            resultado['pasta_matriculas'] = payload.get('pasta_matriculas', resultado['pasta_matriculas'])
            resultado['empreendimentos'] = payload.get('empreendimentos', [])
            resultado['confirmado'] = True
            webview.windows[0].destroy()

    webview.create_window(
        "Configuração da Auditoria - VIC Engenharia",
        html=html_config,
        js_api=_Api(),
        width=880,
        height=880,
        min_size=(720, 640),
        background_color="#0a0808",  # evita flash branco enquanto o HTML carrega
        resizable=True,
    )
    webview.start()  # bloqueia até fechar
    return resultado
