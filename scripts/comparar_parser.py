"""Etapa 6.1: compara o parser determinístico com o modelo real e mostra as divergências.

Gasta centavos de API real. A chave vem só de ANTHROPIC_API_KEY (nunca é impressa):
    $env:ANTHROPIC_API_KEY="..."; python scripts/comparar_parser.py
Para cada mensagem coberta pelo parser, o dict dele tem de ser IDÊNTICO ao do modelo. As mensagens
ambíguas têm de cair no modelo (parser devolve None). Zero divergências libera o merge.
"""
import asyncio
import os
import sys

CHAVE = os.environ["ANTHROPIC_API_KEY"]
os.environ.setdefault("TWILIO_AUTH_TOKEN", "x")
os.environ.setdefault("SUPABASE_URL", "http://x")
os.environ.setdefault("SUPABASE_KEY", "x")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main

# Mensagens que o parser deve cobrir (inclui variações de escrita).
COBERTAS = [
    "oi", "Oi", "OI", "olá", "Ola", "  oi  ", "ajuda", "AJUDA", "Ajuda",
    "saldo", "Saldo", "SALDO", "  saldo ", "quanto tenho", "quanto sobrou",
    "comparar meses", "Comparar  Meses", "comparativo",
    "minhas metas", "Minhas Metas", "metas", "ver metas",
    "meus lembretes", "Meus  Lembretes", "ver lembretes",
    "últimos gastos", "ultimos gastos", "ÚLTIMOS GASTOS",
    "desfazer", "Desfazer", "remover último", "remover ultimo", "REMOVER ÚLTIMO",
    "meta lazer 300", "Meta Alimentação 500", "limite transporte 200", "definir meta saude 150,50",
    "meta educacao 1000", "meta vestuario 80",
]

# Ambíguas: o parser tem de devolver None e o modelo decide como hoje.
AMBIGUAS = [
    "oi, tudo bem?", "saldo de março", "saldo hoje", "uber 27", "mercado 150 pix",
    "recebi salário 3000", "meta mercado 300", "meta lazer 1.500", "remover uber", "remover lazer",
    "desfazer o último", "lembrete aluguel 1200 dia 5", "comparar meses e metas", "quanto gastei no cartão",
]


async def rodar():
    divergencias = []
    for msg in COBERTAS:
        esperado = main.parse_deterministico(msg)
        if esperado is None:
            divergencias.append((msg, "parser devolveu None (devia cobrir)", None))
            continue
        try:
            modelo = await main.interpretar_com_modelo(msg)
        except Exception as e:  # erro de rede/modelo não é divergência de lógica, mas bloqueia o merge
            divergencias.append((msg, f"modelo falhou: {type(e).__name__}", esperado))
            continue
        if modelo != esperado:
            divergencias.append((msg, "dicts diferentes", {"parser": esperado, "modelo": modelo}))
    for msg in AMBIGUAS:
        palpite = main.parse_deterministico(msg)
        if palpite is not None:
            divergencias.append((msg, "parser deu palpite (devia ser None)", palpite))
    return divergencias


def main_():
    assert main.ANTHROPIC_API_KEY == CHAVE
    divergencias = asyncio.run(rodar())
    total = len(COBERTAS) + len(AMBIGUAS)
    print(f"Mensagens: {total} ({len(COBERTAS)} cobertas, {len(AMBIGUAS)} ambíguas)")
    print(f"Divergências: {len(divergencias)}")
    for msg, motivo, detalhe in divergencias:
        print(f"  - {msg!r}: {motivo}\n      {detalhe}")
    print("RESULTADO:", "OK, pode fazer o merge" if not divergencias else "NÃO fazer o merge")
    return 1 if divergencias else 0


if __name__ == "__main__":
    sys.exit(main_())
