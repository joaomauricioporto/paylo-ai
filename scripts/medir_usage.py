"""Mede response.usage do interpretar_mensagem (etapa 5.1). Gasta centavos de API real.

Uso (a chave vem do ambiente, nunca do código):
    ANTHROPIC_API_KEY=... python scripts/medir_usage.py [arquivo.txt]
O arquivo tem uma mensagem por linha; sem ele, usa as de exemplo abaixo.
"""
import os
import sys

os.environ.setdefault("TWILIO_AUTH_TOKEN", "x")
os.environ.setdefault("SUPABASE_URL", "http://x")
os.environ.setdefault("SUPABASE_KEY", "x")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main

EXEMPLOS = ["uber 27", "mercado 150 débito", "almoço 35 pix", "recebi salário 3000", "saldo",
            "resumo da semana", "quanto gastei no cartão", "comparar meses", "meta lazer 300",
            "minhas metas", "lembrete aluguel 1200 dia 5", "meus lembretes", "remover último",
            "remover uber", "extorno 100 transporte", "últimos gastos", "oi", "ajuda"]
# US$ por milhão de tokens (Haiku 5.5, prompt até 100K): entrada, saída, leitura de cache, escrita de cache
ENTRADA, SAIDA, LEITURA, ESCRITA = 0.10, 0.50, 0.010, 0.125

mensagens = open(sys.argv[1], encoding="utf-8").read().splitlines() if len(sys.argv) > 1 else EXEMPLOS
mensagens = [m for m in mensagens if m.strip()]

contagem = main.client.messages.count_tokens(
    model=main.MODELO_IA, system=main.SYSTEM_PROMPT, messages=[{"role": "user", "content": "oi"}])
print(f"System prompt + 'oi': {contagem.input_tokens} tokens (mínimo para cache no Haiku 5.5: 512)\n")

totais = dict(entrada=0, saida=0, escrito=0, lido=0)
for i, m in enumerate(mensagens, 1):
    r = main.client.messages.create(
        model=main.MODELO_IA, max_tokens=400, thinking={"type": "disabled"},
        system=[{"type": "text", "text": main.SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": m}])
    u = r.usage
    print(f"{i:2} {m[:30]:30} entrada={u.input_tokens} saída={u.output_tokens} "
          f"cache_escrito={u.cache_creation_input_tokens} cache_lido={u.cache_read_input_tokens}")
    totais["entrada"] += u.input_tokens; totais["saida"] += u.output_tokens
    totais["escrito"] += u.cache_creation_input_tokens or 0; totais["lido"] += u.cache_read_input_tokens or 0

n = len(mensagens)
com_cache = (totais["entrada"] * ENTRADA + totais["saida"] * SAIDA + totais["lido"] * LEITURA
             + totais["escrito"] * ESCRITA) / 1e6
sem_cache = ((totais["entrada"] + totais["lido"] + totais["escrito"]) * ENTRADA + totais["saida"] * SAIDA) / 1e6
print(f"\n{n} mensagens: {totais}")
print(f"Custo estimado: com cache US$ {com_cache:.5f} | sem cache US$ {sem_cache:.5f} | por mensagem US$ {com_cache / n:.6f}")
