from fastapi import FastAPI, Form
from fastapi.responses import PlainTextResponse
import anthropic
import json
import os
from datetime import datetime, timedelta
import httpx
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SUPABASE_API = f"{SUPABASE_URL}/rest/v1"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

# ============================================================
# BANCO DE DADOS — Supabase
# ============================================================
def salvar_gasto(descricao, valor, categoria, forma_pagamento, telefone):
    data = {
        "data": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "descricao": descricao,
        "valor": valor,
        "categoria": categoria,
        "forma_pagamento": forma_pagamento,
        "telefone": telefone
    }
    url = f"{SUPABASE_API}/gastos"
    r = httpx.post(url, headers=HEADERS, json=data)
    r.raise_for_status()
    resultado = r.json()
    return resultado[0]["id"] if resultado else "?"

def buscar_gastos(telefone, periodo="mes"):
    hoje = datetime.now()
    url = f"{SUPABASE_API}/gastos"
    if periodo == "hoje":
        filtro = hoje.strftime("%Y-%m-%d")
        params = {"telefone": f"eq.{telefone}", "data": f"like.{filtro}%", "order": "id.desc"}
    elif periodo == "semana":
        inicio = (hoje - timedelta(days=7)).strftime("%Y-%m-%d")
        params = {"telefone": f"eq.{telefone}", "data": f"gte.{inicio}", "order": "id.desc"}
    else:
        filtro = hoje.strftime("%Y-%m")
        params = {"telefone": f"eq.{telefone}", "data": f"like.{filtro}%25", "order": "id.desc"}
    r = httpx.get(url, headers=HEADERS, params=params)
    r.raise_for_status()
    return r.json()

def buscar_por_forma_pagamento(telefone, forma, periodo="mes"):
    hoje = datetime.now()
    url = f"{SUPABASE_API}/gastos"
    if periodo == "hoje":
        filtro = hoje.strftime("%Y-%m-%d")
        params = {"telefone": f"eq.{telefone}", "forma_pagamento": f"ilike.%{forma}%", "data": f"like.{filtro}%", "order": "id.desc"}
    elif periodo == "semana":
        inicio = (hoje - timedelta(days=7)).strftime("%Y-%m-%d")
        params = {"telefone": f"eq.{telefone}", "forma_pagamento": f"ilike.%{forma}%", "data": f"gte.{inicio}", "order": "id.desc"}
    else:
        filtro = hoje.strftime("%Y-%m")
        params = {"telefone": f"eq.{telefone}", "forma_pagamento": f"ilike.%{forma}%", "data": f"like.{filtro}%25", "order": "id.desc"}
    r = httpx.get(url, headers=HEADERS, params=params)
    r.raise_for_status()
    return r.json()

def remover_ultimo_gasto(telefone):
    url = f"{SUPABASE_API}/gastos"
    r = httpx.get(url, headers=HEADERS, params={"telefone": f"eq.{telefone}", "order": "id.desc", "limit": "1"})
    r.raise_for_status()
    gastos = r.json()
    if not gastos:
        return None
    gasto = gastos[0]
    httpx.delete(url, headers=HEADERS, params={"id": f"eq.{gasto['id']}"})
    return gasto

def remover_gasto_por_descricao(telefone, descricao):
    url = f"{SUPABASE_API}/gastos"
    r = httpx.get(url, headers=HEADERS, params={"telefone": f"eq.{telefone}", "descricao": f"ilike.%{descricao}%", "order": "id.desc", "limit": "1"})
    r.raise_for_status()
    gastos = r.json()
    if not gastos:
        return None
    gasto = gastos[0]
    httpx.delete(url, headers=HEADERS, params={"id": f"eq.{gasto['id']}"})
    return gasto

def listar_ultimos_gastos(telefone, limite=5):
    url = f"{SUPABASE_API}/gastos"
    r = httpx.get(url, headers=HEADERS, params={"telefone": f"eq.{telefone}", "order": "id.desc", "limit": str(limite)})
    r.raise_for_status()
    return r.json()

# ============================================================
# IA
# ============================================================
SYSTEM_PROMPT = """Você é um assistente financeiro pessoal via WhatsApp chamado Paylo.IA 🐒.
Responda APENAS com JSON válido, sem markdown, sem explicações.

1. REGISTRAR GASTO (ex: "uber 27", "mercado 150 débito", "almoço 35 pix"):
{"tipo": "gasto", "descricao": "descrição", "valor": 27.0, "categoria": "Transporte", "forma_pagamento": "não informado"}
Categorias: Alimentação, Transporte, Lazer, Saúde, Moradia, Educação, Vestuário, Outros

2. RELATÓRIO (ex: "resumo", "quanto gastei hoje", "resumo da semana"):
{"tipo": "relatorio", "periodo": "mes"}
Períodos: hoje, semana, mes

3. RELATÓRIO POR FORMA DE PAGAMENTO (ex: "quanto gastei no cartão", "total no pix", "gastos no débito essa semana"):
{"tipo": "relatorio_pagamento", "forma": "cartão", "periodo": "mes"}
Formas: cartão, pix, débito, dinheiro, crédito

4. REMOVER ÚLTIMO (ex: "remover último", "apagar último", "desfazer"):
{"tipo": "remover_ultimo"}

5. REMOVER ESPECÍFICO (ex: "remover uber", "apagar mercado"):
{"tipo": "remover_item", "descricao": "uber"}

6. HISTÓRICO (ex: "últimos gastos", "o que registrei"):
{"tipo": "historico"}

7. OUTROS (ex: "oi", "ajuda"):
{"tipo": "ajuda"}"""

def interpretar_mensagem(mensagem):
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": mensagem}]
    )
    texto = response.content[0].text.strip()
    if texto.startswith("```"):
        texto = texto.split("```")[1]
        if texto.startswith("json"):
            texto = texto[4:]
    return json.loads(texto.strip())

# ============================================================
# RELATÓRIOS
# ============================================================
def gerar_relatorio(telefone, periodo):
    gastos = buscar_gastos(telefone, periodo)
    if not gastos:
        nomes = {"hoje": "hoje", "semana": "nos últimos 7 dias", "mes": "este mês"}
        return f"📭 Nenhum gasto registrado {nomes.get(periodo, 'neste período')}."

    total = sum(g["valor"] for g in gastos)
    por_categoria = {}
    for g in gastos:
        por_categoria[g["categoria"]] = por_categoria.get(g["categoria"], 0) + g["valor"]

    nomes_periodo = {"hoje": "Hoje", "semana": "Últimos 7 dias", "mes": "Este mês"}
    linhas = [f"📊 *Relatório — {nomes_periodo.get(periodo, 'Período')}*\n"]
    for cat, val in sorted(por_categoria.items(), key=lambda x: -x[1]):
        linhas.append(f"  {cat}: R$ {val:.2f}")
    linhas.append(f"\n💰 *Total: R$ {total:.2f}*")
    return "\n".join(linhas)

def gerar_relatorio_pagamento(telefone, forma, periodo):
    gastos = buscar_por_forma_pagamento(telefone, forma, periodo)
    nomes_periodo = {"hoje": "hoje", "semana": "nos últimos 7 dias", "mes": "este mês"}

    if not gastos:
        return f"📭 Nenhum gasto no {forma} {nomes_periodo.get(periodo, 'neste período')}."

    total = sum(g["valor"] for g in gastos)
    por_categoria = {}
    for g in gastos:
        por_categoria[g["categoria"]] = por_categoria.get(g["categoria"], 0) + g["valor"]

    nomes_periodo2 = {"hoje": "Hoje", "semana": "Últimos 7 dias", "mes": "Este mês"}
    linhas = [f"💳 *{forma.capitalize()} — {nomes_periodo2.get(periodo, 'Período')}*\n"]
    for cat, val in sorted(por_categoria.items(), key=lambda x: -x[1]):
        linhas.append(f"  {cat}: R$ {val:.2f}")
    linhas.append(f"\n💰 *Total no {forma}: R$ {total:.2f}*")
    return "\n".join(linhas)

def gerar_historico(telefone):
    gastos = listar_ultimos_gastos(telefone)
    if not gastos:
        return "📭 Nenhum gasto registrado ainda."
    linhas = ["🧾 *Últimos gastos:*\n"]
    for g in gastos:
        forma = g.get("forma_pagamento", "não informado")
        linhas.append(f"• {g['descricao'].capitalize()} — R$ {g['valor']:.2f} ({g['categoria']} · {forma})")
    return "\n".join(linhas)

# ============================================================
# AJUDA
# ============================================================
MENSAGEM_AJUDA = """🐒 *Olá! Sou o Paylo.IA, seu assistente financeiro!*

*📝 Registrar gastos:*
• "mercado 150"
• "uber 27 pix"
• "almoço 35 cartão"

*📊 Ver relatórios:*
• "resumo" ou "resumo da semana"
• "quanto gastei hoje"

*💳 Por forma de pagamento:*
• "quanto gastei no cartão"
• "total no pix essa semana"
• "gastos no débito hoje"

*🧾 Ver histórico:*
• "últimos gastos"

*🗑️ Remover gastos:*
• "remover último"
• "remover uber"

*💡 Escreva de forma natural, eu entendo! 😊*"""

# ============================================================
# WEBHOOK
# ============================================================
@app.post("/webhook", response_class=PlainTextResponse)
async def webhook(
    Body: str = Form(...),
    From: str = Form(...)
):
    mensagem = Body.strip()
    telefone = From
    logger.info(f"Mensagem recebida de {telefone}: {mensagem}")

    try:
        resultado = interpretar_mensagem(mensagem)
        logger.info(f"Interpretado: {resultado}")

        if resultado["tipo"] == "gasto":
            gasto_id = salvar_gasto(
                descricao=resultado["descricao"],
                valor=resultado["valor"],
                categoria=resultado["categoria"],
                forma_pagamento=resultado.get("forma_pagamento", "não informado"),
                telefone=telefone
            )
            resposta = (
                f"✅ *Gasto registrado!* (#{gasto_id})\n\n"
                f"📌 {resultado['descricao'].capitalize()}\n"
                f"💵 R$ {resultado['valor']:.2f}\n"
                f"🏷️ {resultado['categoria']}\n"
                f"💳 {resultado.get('forma_pagamento', 'não informado').capitalize()}"
            )

        elif resultado["tipo"] == "relatorio":
            resposta = gerar_relatorio(telefone, resultado.get("periodo", "mes"))

        elif resultado["tipo"] == "relatorio_pagamento":
            resposta = gerar_relatorio_pagamento(
                telefone,
                resultado.get("forma", "cartão"),
                resultado.get("periodo", "mes")
            )

        elif resultado["tipo"] == "remover_ultimo":
            gasto = remover_ultimo_gasto(telefone)
            if gasto:
                resposta = f"🗑️ *Gasto removido!*\n\n📌 {gasto['descricao'].capitalize()} — R$ {gasto['valor']:.2f}"
            else:
                resposta = "📭 Nenhum gasto encontrado para remover."

        elif resultado["tipo"] == "remover_item":
            gasto = remover_gasto_por_descricao(telefone, resultado.get("descricao", ""))
            if gasto:
                resposta = f"🗑️ *Gasto removido!*\n\n📌 {gasto['descricao'].capitalize()} — R$ {gasto['valor']:.2f}"
            else:
                resposta = "❌ Não encontrei nenhum gasto com esse nome."

        elif resultado["tipo"] == "historico":
            resposta = gerar_historico(telefone)

        else:
            resposta = MENSAGEM_AJUDA

    except Exception as e:
        logger.error(f"Erro ao processar mensagem: {e}")
        resposta = "⚠️ Não entendi sua mensagem. Tente:\n• 'mercado 50'\n• 'resumo'\n• 'quanto gastei no cartão'"

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{resposta}</Message>
</Response>"""
    return PlainTextResponse(content=twiml, media_type="application/xml")

@app.get("/")
def health():
    return {"status": "Paylo.IA rodando! 🐒", "supabase_api": SUPABASE_API}
