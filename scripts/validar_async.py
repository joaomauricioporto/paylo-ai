"""Valida a etapa 6.3 (async + timeouts) com a API real da Anthropic: 15 mensagens pelo webhook.

Gasta centavos de API real. A chave vem só de ANTHROPIC_API_KEY (nunca do código):
    ANTHROPIC_API_KEY=... python scripts/validar_async.py
Passa cada mensagem por POST /webhook (assinado, em memória, no mesmo event loop) com o AsyncAnthropic
de verdade. O Supabase NÃO é tocado: é um banco falso em memória (httpx.MockTransport) que começa
vazio, então as respostas esperadas são as de "nada cadastrado ainda". Mostra:
  1. a resposta de cada mensagem e se bate com o esperado (e a latência);
  2. o uso de tokens (cache_escrito/cache_lido) para ver que o cache segue funcionando no cliente async;
  3. um lote de 5 mensagens ao mesmo tempo: o tempo total deve ficar bem abaixo da soma das latências.
Termina com código 1 se alguma resposta divergir ou vier "problema técnico" / "Não entendi".
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")  # o console do Windows (cp1252) não imprime ✓/✗
if not os.getenv("ANTHROPIC_API_KEY"):
    sys.exit("Defina ANTHROPIC_API_KEY no ambiente para rodar este script.")

# Sobrescreve (não usa setdefault) para que este script nunca fale com o Supabase nem com o token reais.
os.environ["TWILIO_AUTH_TOKEN"] = "token-de-teste"
os.environ["SUPABASE_URL"] = "http://supabase.invalido"
os.environ["SUPABASE_KEY"] = "chave-de-teste"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
import re
import time
from html import unescape

import httpx
from twilio.request_validator import RequestValidator

import main

URL = "http://testserver/webhook"

# (mensagem, trecho esperado na resposta). Banco vazio: gravações confirmam, consultas dizem "nenhum".
CASOS = [
    ("uber 27", "Gasto registrado"),
    ("almoço 35 pix", "Gasto registrado"),
    ("recebi salário 3000", "Receita registrada"),
    ("resumo da semana", "Nenhum gasto registrado nos últimos 7 dias"),
    ("como tá meu saldo?", "Saldo"),
    ("comparar meses", "Comparativo de Meses"),
    ("meta lazer 300", "Meta criada"),
    ("minhas metas", "Nenhuma meta definida"),
    ("lembrete aluguel 1200 dia 5", "Lembrete adicionado"),
    ("meus lembretes", "Nenhum lembrete cadastrado"),
    ("remover lembrete aluguel", "Lembrete não encontrado"),
    ("desfazer", "Nenhum gasto para remover"),
    ("remover uber", "Gasto não encontrado"),
    ("últimos gastos", "Nenhum gasto registrado ainda"),
    ("oi", "Paylo.IA"),
]
LOTE = ["uber 27", "recebi salário 3000", "como tá meu saldo?", "meta lazer 300", "oi"]


def supabase_falso():
    """PostgREST mínimo e vazio: GET devolve [], POST devolve a linha com id, o resto responde 204."""
    ids = iter(range(1, 10_000))

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, json=[])
        if req.method == "POST":
            if req.headers.get("prefer") == "return=minimal":
                return httpx.Response(201)
            return httpx.Response(201, json=[{"id": next(ids), **json.loads(req.content)}])
        return httpx.Response(204)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=main.TIMEOUT_SUPABASE)


class Medidor:
    """Envolve client.messages.create para somar o uso de tokens sem mexer no código de produção."""

    def __init__(self):
        self.usos = []
        original = main.client.messages.create

        async def create(**kwargs):
            r = await original(**kwargs)
            self.usos.append(r.usage)
            return r

        main.client.messages.create = create


async def enviar(app_client, mensagem, sid):
    form = {"Body": mensagem, "From": "whatsapp:+5511999999999", "MessageSid": sid}
    assinatura = RequestValidator("token-de-teste").compute_signature(URL, form)
    t0 = time.monotonic()
    r = await app_client.post("/webhook", data=form, headers={"X-Twilio-Signature": assinatura})
    achado = re.search(r"<Message>(.*)</Message>", r.text, re.S)
    return r.status_code, unescape(achado.group(1)) if achado else "", time.monotonic() - t0


async def rodar():
    print(f"Timeouts: Anthropic read={main.client.timeout.read}s connect={main.client.timeout.connect}s "
          f"retries={main.client.max_retries} | Supabase read={main.TIMEOUT_SUPABASE.read}s "
          f"teto por chamada={main.TEMPO_MAX_SUPABASE}s\n")
    main._db = supabase_falso()
    medidor = Medidor()
    problemas = 0
    soma = 0.0
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://testserver") as c:
        for i, (mensagem, esperado) in enumerate(CASOS, 1):
            status, resposta, seg = await enviar(c, mensagem, f"SM-async-{i}")
            soma += seg
            ruim = status != 200 or esperado not in resposta or "problema técnico" in resposta \
                or "Não entendi" in resposta
            problemas += ruim
            primeira = resposta.splitlines()[0] if resposta else "(vazia)"
            print(f"{'✗' if ruim else '✓'} {mensagem!r:32} {seg:5.2f}s  {primeira}")
            if ruim:
                print(f"    esperava conter {esperado!r}; status {status}; resposta: {resposta!r}")

        print(f"\nLote de {len(LOTE)} mensagens ao mesmo tempo (cache já aquecido):")
        t0 = time.monotonic()
        resultados = await asyncio.gather(*(enviar(c, m, f"SM-lote-{i}") for i, m in enumerate(LOTE)))
        total = time.monotonic() - t0
        for m, (status, resposta, seg) in zip(LOTE, resultados):
            ruim = status != 200 or "problema técnico" in resposta or "Não entendi" in resposta
            problemas += ruim
            print(f"{'✗' if ruim else '✓'} {m!r:32} {seg:5.2f}s")
        soma_lote = sum(r[2] for r in resultados)
        print(f"  tempo total {total:.2f}s contra {soma_lote:.2f}s se fossem em fila "
              f"({'ok, concorrente' if total < soma_lote * 0.7 else 'ATENÇÃO: parece serializado'})")

    escrito = sum(u.cache_creation_input_tokens or 0 for u in medidor.usos)
    lido = sum(u.cache_read_input_tokens or 0 for u in medidor.usos)
    print(f"\nUso: {len(medidor.usos)} chamadas ao modelo, entrada={sum(u.input_tokens for u in medidor.usos)} "
          f"saída={sum(u.output_tokens for u in medidor.usos)} cache_escrito={escrito} cache_lido={lido}")
    print(f"Sequencial: {soma / len(CASOS):.2f}s por mensagem em média.")
    print(f"\n{len(CASOS) + len(LOTE) - problemas}/{len(CASOS) + len(LOTE)} ok; {problemas} com problema.")
    await main._db.aclose()
    await main.client.close()
    return 1 if problemas else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(rodar()))
