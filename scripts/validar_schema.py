"""Valida com a API real o schema de saída estruturada da etapa 5.2 (16 mensagens, uma por intenção).

Gasta centavos de API real. A chave vem só de ANTHROPIC_API_KEY (nunca do código):
    ANTHROPIC_API_KEY=... python scripts/validar_schema.py
Chama main.interpretar_mensagem, o mesmo caminho da produção, e mostra:
  1. se a API aceitou o schema (um 400 na primeira chamada interrompe o script);
  2. se o dict devolvido bate com o esperado em tipo, valores e campos principais.
Não grava nada no Supabase. Termina com código 1 se o schema foi recusado ou algum caso divergiu.
"""
import os
import sys

if not os.getenv("ANTHROPIC_API_KEY"):
    sys.exit("Defina ANTHROPIC_API_KEY no ambiente para rodar este script.")

os.environ.setdefault("TWILIO_AUTH_TOKEN", "x")
os.environ.setdefault("SUPABASE_URL", "http://x")
os.environ.setdefault("SUPABASE_KEY", "x")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic

import main

# (mensagem, campos esperados no dict). Categoria e descrição não entram: dependem de interpretação livre.
CASOS = [
    ("uber 27", {"tipo": "gasto", "valor": 27.0}),
    ("almoço 35 pix", {"tipo": "gasto", "valor": 35.0, "forma_pagamento": "pix"}),
    ("recebi salário 3000", {"tipo": "receita", "valor": 3000.0}),
    ("quanto gastei hoje", {"tipo": "relatorio", "periodo": "hoje"}),
    ("resumo da semana", {"tipo": "relatorio", "periodo": "semana"}),
    ("quanto gastei no cartão esse mês", {"tipo": "relatorio_pagamento", "forma": "cartão", "periodo": "mes"}),
    ("como tá meu saldo?", {"tipo": "saldo"}),
    ("comparar meses", {"tipo": "comparativo"}),
    ("meta lazer 300", {"tipo": "definir_meta", "limite": 300.0}),
    ("minhas metas", {"tipo": "ver_metas"}),
    ("lembrete aluguel 1200 dia 5", {"tipo": "adicionar_lembrete", "valor": 1200.0, "dia_vencimento": 5}),
    ("meus lembretes", {"tipo": "ver_lembretes"}),
    ("remover lembrete aluguel", {"tipo": "remover_lembrete"}),
    ("desfazer", {"tipo": "remover_ultimo"}),
    ("remover uber", {"tipo": "remover_item"}),
    ("extorno 100 transporte", {"tipo": "remover_categoria", "valor": 100.0}),
    ("últimos gastos", {"tipo": "historico"}),
    ("oi", {"tipo": "ajuda"}),
]


def confere(obtido, esperado):
    """Devolve a lista de campos que não batem (vazia = ok)."""
    return [f"{k}: esperava {v!r}, veio {obtido.get(k)!r}" for k, v in esperado.items()
            if str(obtido.get(k)).lower() != str(v).lower()]


def main_():
    ok = 0
    divergentes = 0
    for i, (mensagem, esperado) in enumerate(CASOS, 1):
        try:
            obtido = main.interpretar_mensagem(mensagem)
        except anthropic.BadRequestError as e:
            print(f"✗ A API RECUSOU o pedido/schema na mensagem {i} ({mensagem!r}):\n  {e.message}")
            if i == 1:
                print("\nSchema não aceito: nada mais foi testado.")
                return 1
            divergentes += 1
            continue
        except anthropic.APIError as e:
            print(f"✗ {mensagem!r}: erro de API ({type(e).__name__}): {e}")
            divergentes += 1
            continue
        except main.ErroInterpretacao as e:
            print(f"✗ {mensagem!r}: fora do schema: {e}")
            divergentes += 1
            continue
        if i == 1:
            print("✓ A API aceitou o schema.\n")
        faltas = confere(obtido, esperado)
        if faltas:
            divergentes += 1
            print(f"≠ {mensagem!r} -> {obtido}\n    " + "\n    ".join(faltas))
        else:
            ok += 1
            print(f"✓ {mensagem!r} -> {obtido}")
    print(f"\n{ok}/{len(CASOS)} batem com o esperado; {divergentes} com problema.")
    return 1 if divergentes else 0


if __name__ == "__main__":
    sys.exit(main_())
