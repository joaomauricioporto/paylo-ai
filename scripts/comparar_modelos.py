"""Compara claude-haiku-5-5 e claude-sonnet-4-6 em 30 mensagens e mostra só onde divergem.

Gasta centavos de API real. A chave vem só de ANTHROPIC_API_KEY (nunca do código):
    ANTHROPIC_API_KEY=... python scripts/comparar_modelos.py
Compara tipo, valor (ou limite, nas metas) e categoria. Não há gabarito: mostra onde os
dois modelos discordam, não qual está certo.
"""
import json
import os
import sys

os.environ.setdefault("TWILIO_AUTH_TOKEN", "x")
os.environ.setdefault("SUPABASE_URL", "http://x")
os.environ.setdefault("SUPABASE_KEY", "x")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import anthropic

import main

MODELOS = ["claude-haiku-5-5", "claude-sonnet-4-6"]

MENSAGENS = [
    # gastos
    "gastei 40 no mercado ontem, pix", "uber 27", "almoço 35 pix", "paguei 89,90 de luz no débito",
    "comprei remédio 23 e 50", "cinema 48 cartão", "ifood 62 crédito", "gasolina 200",
    # receitas
    "recebi salário 3000", "caiu 500 do freela", "entrada 1200", "ganhei 150 de presente da vó",
    # relatórios, saldo, histórico
    "quanto gastei hoje", "resumo da semana", "quanto gastei no cartão esse mês", "como tá meu saldo?",
    "comparar com o mês passado", "o que eu registrei por último",
    # metas
    "meta lazer 300", "limite de alimentação 800", "como estão minhas metas",
    # lembretes
    "lembrete aluguel 1200 dia 5", "conta de luz 80 vence dia 10", "meus lembretes", "apaga o lembrete da luz",
    # remoções
    "desfaz o último", "remover uber", "extorno 100 transporte",
    # ambíguas e bagunçadas
    "oi", "mercado 150 uber 30 pix",
]


def interpretar(cliente, modelo, mensagem):
    """Mesmo pedido de main.interpretar_mensagem, com o modelo escolhido. Devolve (dict|erro, usage)."""
    pedido = dict(
        model=modelo,
        max_tokens=400,
        system=[{"type": "text", "text": main.SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": mensagem}],
    )
    if modelo == "claude-haiku-5-5":
        pedido["thinking"] = {"type": "disabled"}  # como na produção; o Sonnet 4.6 não pensa sem pedir
    try:
        r = cliente.messages.create(**pedido)
    except anthropic.APIError as e:
        return f"ERRO API: {e}", None
    texto = next((b.text for b in r.content if b.type == "text"), "").strip()
    if texto.startswith("```"):
        texto = texto.split("```")[1]
        if texto.startswith("json"):
            texto = texto[4:]
    try:
        resultado = json.loads(texto.strip())
        if not isinstance(resultado, dict) or "tipo" not in resultado:
            raise ValueError("sem 'tipo'")
    except ValueError:
        return f"JSON INVÁLIDO: {texto[:80]!r}", r.usage
    return resultado, r.usage


def campos(resultado):
    if not isinstance(resultado, dict):
        return {"tipo": resultado, "valor": None, "categoria": None}
    valor = resultado.get("valor", resultado.get("limite"))
    return {"tipo": resultado["tipo"], "valor": None if valor is None else float(valor),
            "categoria": resultado.get("categoria")}


def main_():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Defina ANTHROPIC_API_KEY no ambiente.")
    cliente = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    print("Tokens do system prompt por modelo (mínimo p/ cache: Haiku 5.5 = 512, Sonnet 4.6 = 1024):")
    for m in MODELOS:
        n = cliente.messages.count_tokens(
            model=m, system=main.SYSTEM_PROMPT, messages=[{"role": "user", "content": "oi"}]).input_tokens
        print(f"  {m}: {n}")

    usos = {m: dict(entrada=0, saida=0, escrito=0, lido=0) for m in MODELOS}
    divergencias = 0
    falhas = []  # mensagens em que algum modelo não devolveu JSON utilizável
    for i, msg in enumerate(MENSAGENS, 1):
        achados = {}
        for m in MODELOS:
            achados[m], u = interpretar(cliente, m, msg)
            if u:
                t = usos[m]
                t["entrada"] += u.input_tokens
                t["saida"] += u.output_tokens
                t["escrito"] += u.cache_creation_input_tokens or 0
                t["lido"] += u.cache_read_input_tokens or 0
        if any(isinstance(achados[m], str) for m in MODELOS):
            falhas.append(i)
        a, b = (campos(achados[m]) for m in MODELOS)
        difs = [k for k in ("tipo", "valor", "categoria") if a[k] != b[k]]
        if difs:
            divergencias += 1
            print(f"\n[{i:2}] {msg!r}  diverge em: {', '.join(difs)}")
            for m in MODELOS:
                print(f"     {m:18} {achados[m]}")

    print(f"\n{divergencias} de {len(MENSAGENS)} mensagens com divergência em tipo, valor ou categoria.")
    if falhas:
        print(f"Mensagens com erro de API ou JSON inválido em algum modelo (iguais nos dois não aparecem acima): {falhas}")
    print("Uso total (cache_escrito > 0 e cache_lido > 0 = o cache funcionou):")
    for m in MODELOS:
        print(f"  {m}: {usos[m]}")


if __name__ == "__main__":
    main_()
