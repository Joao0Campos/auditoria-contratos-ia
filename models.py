from typing import List, Literal
from pydantic import BaseModel

class Divergencia(BaseModel):
    gravidade: Literal["CRITICO", "MODERADO"]
    campo: str
    valor_encontrado: str
    documento_origem: str
    valor_esperado: str

class ResultadoAuditoria(BaseModel):
    # "divergencias" vem ANTES de "status" de propósito: força o modelo a listar
    # (ou não) os problemas encontrados antes de decidir o status, reduzindo o
    # caso em que ele marca DIVERGENCIA e só depois "inventa" um item pra justificar.
    divergencias: List[Divergencia] = []
    status: Literal["OK", "DIVERGENCIA"]
