from utils.system import configurar_saida_utf8, desabilitar_quickedit
from core.audit_runner import AuditRunner

def main():
    configurar_saida_utf8()
    # desabilitar_quickedit() # Descomente se for rodar fora do VS Code

    runner = AuditRunner()
    runner.run()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[ERRO CRÍTICO NO SISTEMA] A execução foi interrompida:")
        print(f"Detalhes técnicos: {e}")
    finally:
        print("\n")
        input("Operação finalizada. Pressione ENTER para fechar a janela...")
