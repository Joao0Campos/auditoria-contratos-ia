import os
import sys
import ctypes

def configurar_saida_utf8():
    """Força saída em UTF-8 (evita UnicodeEncodeError com nomes acentuados)."""
    if os.name == 'nt':
        try:
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass

    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, 'reconfigure'):
                stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

def desabilitar_quickedit():
    """Trava anti-pausa do console Windows (QuickEdit)."""
    if os.name == 'nt':
        try:
            STD_INPUT_HANDLE = -10
            ENABLE_QUICK_EDIT_MODE = 0x0040
            ENABLE_EXTENDED_FLAGS = 0x0080

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(STD_INPUT_HANDLE)
            modo_atual = ctypes.c_uint()

            kernel32.GetConsoleMode(handle, ctypes.byref(modo_atual))

            novo_modo = modo_atual.value & ~ENABLE_QUICK_EDIT_MODE
            novo_modo = novo_modo | ENABLE_EXTENDED_FLAGS

            kernel32.SetConsoleMode(handle, novo_modo)
        except Exception as e:
            print(f"[Aviso] Não foi possível configurar o console: {e}")
