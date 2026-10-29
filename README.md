# Auditoria de Contratos Imobiliários com IA

Ferramenta em Python que audita, em lote, contratos de financiamento imobiliário (CEF) antes do envio ao banco. Ela cruza cada contrato em PDF com a planilha oficial de vendas e com os documentos de apoio do empreendimento, usando o Google Gemini com **saída estruturada**, e devolve uma planilha Excel com o status de cada contrato e uma linha por divergência encontrada.

## Problema

Contratos com dados divergentes (nome, CPF, RG/CNH, endereço/CEP, CNPJ do empreendimento, matrícula do imóvel, áreas, vaga de garagem) voltam do banco com exigência de correção, o que atrasa o processo. A conferência manual exige ler cada contrato e compará-lo com várias fontes ao mesmo tempo.

## Solução

Para cada PDF de contrato, o sistema:

1. Identifica a venda pelo código no nome do arquivo e localiza a linha correspondente na planilha oficial (o "gabarito").
2. Anexa os documentos de apoio: contrato(s) de abertura de crédito do empreendimento (PJ), a matrícula individualizada do imóvel (quando existir) ou, na falta dela, o quadro de áreas/vagas da NBR 12.721 em texto.
3. Envia tudo ao Gemini com um prompt de auditoria passo a passo (`prompt_auditoria.txt`) e um schema Pydantic como formato de resposta.
4. Filtra falsos positivos com regras determinísticas, classifica a gravidade (CRÍTICO/MODERADO) e grava o resultado no Excel com checkpoints.

## Stack

- Python 3
- Google Gemini (`google-genai`): Files API para os PDFs e `generate_content` com `response_schema`
- Pydantic: schema da resposta (`models.py`)
- pandas + openpyxl: leitura da planilha e gravação do Excel formatado
- pywebview: janela de configuração (HTML/CSS/JS) com ponte JS↔Python e seletor de pastas nativo

## Arquitetura e fluxo

```
main.py
 └─ core/audit_runner.py (AuditRunner)
     ├─ services/excel_service.py   verifica se a planilha está gravável; salva as 3 abas formatadas
     ├─ services/nbr_service.py     carrega o consolidado NBR 12.721 e acha o empreendimento
     ├─ services/pdf_service.py     localiza os contratos PJ do empreendimento (inclusive por módulo)
     ├─ ui/config_window.py         janela pywebview: pastas de origem + filtro de empreendimentos
     ├─ utils/formatters.py         normalização de texto/códigos e filtro de divergências falsas
     ├─ models.py                   schema Pydantic da resposta do modelo
     └─ prompt_auditoria.txt        prompt com o fluxo de auditoria (passos 1 a 5)
```

1. **Pré-checagens:** confirma que a planilha não está aberta no Excel antes de gastar cota de API. Também confirma que a chave existe.
2. **Configuração:** a janela pywebview lista os empreendimentos da planilha e as pastas de origem.
3. **Preparação:** indexa os códigos de venda (mais longos primeiro, com borda de dígito, para evitar casamento parcial). Depois reaproveita os contratos PJ que já estão na Files API (pelo `display_name`) e sobe só os que faltam.
4. **Processamento:** um `ThreadPoolExecutor` percorre os PDFs. Para cada contrato:
   - pula os já marcados como processados, o que permite retomar a execução;
   - confere se o nome do cliente bate com o nome do arquivo (trava contra colisão de código);
   - envia o PDF e a matrícula, quando houver, e chama o modelo com `temperature=0`;
   - faz até 5 tentativas, com backoff em caso de 429/503 ou de resposta fora do schema;
   - apaga da Files API os arquivos enviados só para aquele contrato.
5. **Saída:** `Sem_Registro.xlsx` é regravado com três abas:
   - `Base`: os dados originais;
   - `Auditoria_CEF`: uma linha por contrato, com status, gravidade e motivo;
   - `Divergencias`: uma linha por divergência, sem células mescladas, para facilitar filtros e tabelas dinâmicas.

## Decisões técnicas

- **Saída estruturada em vez de texto livre:** o modelo preenche um schema Pydantic. No schema, a lista `divergencias` vem antes de `status`, para que o modelo liste os problemas antes de decidir o veredito.
- **Defesa em camadas contra falsos positivos:** além das regras de normalização no prompt, `eh_divergencia_real()` descarta divergências cujo valor encontrado e esperado são iguais após remover acentos e pontuação. Também descarta nome comercial vs. razão social do empreendimento quando um é prefixo do outro.
- **Fonte de verdade hierárquica:** a matrícula individualizada tem prioridade. O quadro NBR só entra no prompt quando não há matrícula anexada.
- **Robustez operacional:**
  - gravação atômica (arquivo temporário + `os.replace`);
  - checkpoint a cada N contratos;
  - retentativa quando o Excel está aberto;
  - *circuit breaker* que interrompe o lote após N falhas seguidas (por exemplo, saldo da API esgotado), deixando os pendentes para a próxima execução.
- **Custo e cota:** os contratos PJ são enviados uma vez e reaproveitados entre execuções. Um atraso configurável entre chamadas respeita o rate limit do free tier.
- **Configuração por ambiente:** chave, modelo, paralelismo, atraso e pasta de dados vêm de variáveis de ambiente ou de um `.env` (veja `.env.example`).

## Como rodar

Pré-requisitos: Python 3.10+ e uma chave da API do Gemini.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env   # preencha GEMINI_API_KEY
.\run.ps1                # ou: python main.py
```

O `run.ps1` usa `GEMINI_API_KEY` se ela já estiver definida no ambiente. Caso contrário, lê o `.env`.

Dados esperados em `AUDITORIA_DIR_BASE` (por padrão, a pasta do projeto). **Nenhum deles está versionado.**

| Item | Conteúdo |
|---|---|
| `Sem_Registro.xlsx` | Planilha oficial (aba `Auditoria_CEF` ou a primeira). Colunas usadas: `NUM_VENDA`, `NOME`, `CGCCFO` (CPF), `CIDENTIDADE` (RG), `CNH`, `ENDERECO`, `Empreendimento` |
| `CONTRATOS_GERAIS/` | PDFs dos contratos CEF; o nome do arquivo contém o código da venda e o nome do cliente |
| `PJ_GERAIS/` | PDFs dos contratos de abertura de crédito, nomeados pelo empreendimento (opcionalmente com sufixo de módulo) |
| `MATRICULAS/` | PDFs das matrículas, com o nome do cliente no nome do arquivo |
| `consolidado.xlsx` | (Opcional) quadros NBR 12.721, uma aba por empreendimento |

## Estrutura

```
.
├── main.py                  ponto de entrada
├── config.py                configuração via ambiente, caminhos e paleta do Excel
├── models.py                schema Pydantic da resposta
├── prompt_auditoria.txt     prompt de auditoria
├── core/audit_runner.py     orquestração do lote
├── services/                Excel, NBR e localização de PDFs
├── ui/                      janela de configuração (pywebview + HTML)
├── utils/                   normalização de texto e ajustes de console
├── run.ps1                  script de execução (Windows)
├── .env.example
└── requirements.txt
```

## Limitações conhecidas

- Não há testes automatizados no repositório.
- Depende de convenções de nome de arquivo (código da venda e nome do cliente no PDF; nome do empreendimento nos contratos PJ).
- O resultado é um apoio à conferência, não uma garantia: o modelo pode errar, e os filtros pós-resposta reduzem, mas não eliminam, falsos positivos e negativos.
- Por padrão, processa um contrato por vez, com pausa entre chamadas, para caber no rate limit do free tier. O paralelismo é configurável.
- A janela de configuração e o `run.ps1` foram feitos para Windows. O `run.ps1` exige o PowerShell. A janela usa o pywebview, que é multiplataforma, mas o projeto não foi verificado fora do Windows.

## Sobre a confidencialidade

O projeto foi desenvolvido para uso interno numa incorporadora. Esta cópia não traz nenhum dado real: contratos, matrículas, planilhas, backups e chaves de API foram removidos. Ficaram o código e o prompt de auditoria. Os nomes de empreendimentos que aparecem como exemplos no prompt e nos comentários são nomes comerciais públicos, sem dados de clientes. O antigo `Completo.py` ficou de fora: era só um *wrapper* de compatibilidade que chamava `main.main()`, e o `run.ps1` agora executa `main.py` diretamente.
