"""Etapa 6.4: corrida nas remoções.

Sem rede externa: o Supabase é um httpx.MockTransport com um banco em memória que apaga de
forma atômica (como o Postgres) e devolve a linha apagada.
"""
import asyncio
import os

os.environ["TWILIO_AUTH_TOKEN"] = "token-de-teste"
os.environ["ANTHROPIC_API_KEY"] = "chave-de-teste"
os.environ["SUPABASE_URL"] = "http://supabase.invalido"
os.environ["SUPABASE_KEY"] = "chave-de-teste"

import httpx
import pytest
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

import main

URL = "http://testserver/webhook"
TEL = "whatsapp:+5511999999999"
OUTRO = "whatsapp:+5511888888888"


class BancoFalso:
    """Tabelas em memória. O GET demora um pouco para que duas remoções leiam antes de qualquer DELETE."""

    def __init__(self):
        self.tabelas = {
            "gastos": [
                {"id": 1, "telefone": TEL, "descricao": "mercado", "valor": 150.0, "categoria": "Alimentação"},
                {"id": 2, "telefone": TEL, "descricao": "uber", "valor": 20.0, "categoria": "Transporte"},
                {"id": 3, "telefone": OUTRO, "descricao": "uber", "valor": 99.0, "categoria": "Transporte"},
            ],
            "lembretes": [{"id": 1, "telefone": TEL, "descricao": "aluguel", "valor": 1000.0, "dia_vencimento": 5}],
        }
        self.requisicoes = []

    def _filtrar(self, tabela, params):
        linhas = self.tabelas[tabela]
        for campo in ("id", "telefone"):
            if campo in params:
                esperado = params[campo].removeprefix("eq.")
                linhas = [l for l in linhas if str(l[campo]) == esperado]
        return linhas

    async def __call__(self, req):
        self.requisicoes.append(req)
        caminho = req.url.path.removeprefix("/rest/v1/")
        params = dict(req.url.params)
        if req.method == "GET":
            await asyncio.sleep(0.05)
            linhas = sorted(self._filtrar(caminho, params), key=lambda l: -l["id"])
            return httpx.Response(200, json=linhas[: int(params.get("limit", 1000))])
        if req.method == "DELETE":
            if "telefone" not in params:  # o DELETE sem filtro de telefone seria um furo
                return httpx.Response(400, json={"message": "sem telefone"})
            apagadas = self._filtrar(caminho, params)
            self.tabelas[caminho] = [l for l in self.tabelas[caminho] if l not in apagadas]
            return httpx.Response(200, json=apagadas)
        if req.method == "POST" and caminho == "rpc/remover_ultimo_gasto":
            tel = req.read().decode()
            assert TEL in tel or OUTRO in tel
            proprios = sorted(self._filtrar("gastos", {"telefone": "eq." + (TEL if TEL in tel else OUTRO)}),
                              key=lambda l: -l["id"])
            if not proprios:
                return httpx.Response(200, json=[])
            self.tabelas["gastos"].remove(proprios[0])
            return httpx.Response(200, json=[proprios[0]])
        return httpx.Response(500)


@pytest.fixture
def banco(monkeypatch):
    banco = BancoFalso()
    monkeypatch.setattr(main, "_db", httpx.AsyncClient(transport=httpx.MockTransport(banco),
                                                       timeout=main.TIMEOUT_SUPABASE))

    async def registrar_mensagem(sid, telefone):
        return True

    monkeypatch.setattr(main, "registrar_mensagem", registrar_mensagem)
    return banco


def interpretar_como(monkeypatch, resultado):
    async def interpretar(mensagem):
        return resultado

    monkeypatch.setattr(main, "interpretar_mensagem", interpretar)


def post(sid="SM1", telefone=TEL):
    form = {"Body": "x", "From": telefone, "MessageSid": sid}
    assinatura = RequestValidator("token-de-teste").compute_signature(URL, form)
    return TestClient(main.app).post("/webhook", data=form, headers={"X-Twilio-Signature": assinatura})


# ---------- remoção normal ----------

def test_remover_ultimo_usa_a_funcao_sql_e_responde_com_o_que_foi_apagado(banco, monkeypatch):
    interpretar_como(monkeypatch, {"tipo": "remover_ultimo"})
    r = post()
    assert "Gasto removido" in r.text and "Uber" in r.text and "R$ 20.00" in r.text
    assert [g["id"] for g in banco.tabelas["gastos"] if g["telefone"] == TEL] == [1]
    assert any(q.url.path.endswith("rpc/remover_ultimo_gasto") for q in banco.requisicoes)
    assert not any(q.method == "DELETE" for q in banco.requisicoes)


def test_remover_ultimo_sem_gastos(banco, monkeypatch):
    interpretar_como(monkeypatch, {"tipo": "remover_ultimo"})
    banco.tabelas["gastos"] = []
    assert "Nenhum gasto para remover" in post().text


def test_remover_item_apaga_so_do_usuario_e_filtra_por_telefone(banco, monkeypatch):
    interpretar_como(monkeypatch, {"tipo": "remover_item", "descricao": "uber"})
    r = post()
    assert "Gasto removido" in r.text and "R$ 20.00" in r.text
    assert {g["id"] for g in banco.tabelas["gastos"]} == {1, 3}  # o uber do outro telefone fica
    deletes = [q for q in banco.requisicoes if q.method == "DELETE"]
    assert len(deletes) == 1
    assert deletes[0].url.params["id"] == "eq.2" and deletes[0].url.params["telefone"] == f"eq.{TEL}"
    assert deletes[0].headers["prefer"] == "return=representation"


def test_remover_categoria_e_lembrete_filtram_por_telefone(banco, monkeypatch):
    interpretar_como(monkeypatch, {"tipo": "remover_categoria", "categoria": "Alimentação", "valor": None})
    assert "Mercado" in post().text
    interpretar_como(monkeypatch, {"tipo": "remover_lembrete", "descricao": "aluguel"})
    assert "Lembrete removido" in post("SM2").text
    assert banco.tabelas["lembretes"] == []
    for q in banco.requisicoes:
        if q.method == "DELETE":
            assert q.url.params["telefone"] == f"eq.{TEL}"


# ---------- item inexistente ----------

def test_item_inexistente_responde_nao_encontrado(banco, monkeypatch):
    interpretar_como(monkeypatch, {"tipo": "remover_item", "descricao": "cinema"})
    assert "Gasto não encontrado" in post().text
    interpretar_como(monkeypatch, {"tipo": "remover_lembrete", "descricao": "luz"})
    assert "Lembrete não encontrado" in post("SM2").text
    assert len(banco.tabelas["gastos"]) == 3


def test_item_que_sumiu_entre_o_select_e_o_delete_vira_nao_encontrado(banco, monkeypatch):
    """O SELECT achou o gasto, mas outro processo o apagou antes do DELETE: o DELETE devolve []."""
    interpretar_como(monkeypatch, {"tipo": "remover_item", "descricao": "uber"})
    original = banco.__call__

    async def apaga_antes_do_delete(req):
        if req.method == "DELETE":
            banco.tabelas["gastos"] = [g for g in banco.tabelas["gastos"] if g["id"] != 2]
        return await original(req)

    monkeypatch.setattr(main, "_db", httpx.AsyncClient(transport=httpx.MockTransport(apaga_antes_do_delete),
                                                       timeout=main.TIMEOUT_SUPABASE))
    r = post()
    assert "Gasto não encontrado" in r.text and "removido" not in r.text


# ---------- duas remoções ao mesmo tempo ----------

def test_duas_remocoes_simultaneas_do_mesmo_item_so_uma_apaga(banco):
    async def cenario():
        return await asyncio.gather(
            main.remover_gasto_por_descricao(TEL, "uber"),
            main.remover_gasto_por_descricao(TEL, "uber"),
        )

    resultados = asyncio.run(cenario())
    apagados = [r for r in resultados if r]
    assert len(apagados) == 1 and apagados[0]["id"] == 2
    assert resultados.count(None) == 1
    assert {g["id"] for g in banco.tabelas["gastos"]} == {1, 3}


def test_duas_mensagens_simultaneas_pelo_webhook_so_uma_apaga(banco, monkeypatch):
    interpretar_como(monkeypatch, {"tipo": "remover_item", "descricao": "uber"})

    async def cenario():
        transporte = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transporte, base_url="http://testserver") as c:
            def req(sid):
                form = {"Body": "remover uber", "From": TEL, "MessageSid": sid}
                assinatura = RequestValidator("token-de-teste").compute_signature(URL, form)
                return c.post("/webhook", data=form, headers={"X-Twilio-Signature": assinatura})

            return await asyncio.gather(req("SM1"), req("SM2"))

    respostas = [r.text for r in asyncio.run(cenario())]
    assert sum("Gasto removido" in t for t in respostas) == 1
    assert sum("Gasto não encontrado" in t for t in respostas) == 1
    assert not any("técnico" in t for t in respostas)
    assert {g["id"] for g in banco.tabelas["gastos"]} == {1, 3}


# ---------- erro do Supabase ----------

@pytest.mark.parametrize("tipo,extra", [
    ("remover_ultimo", {}),
    ("remover_item", {"descricao": "uber"}),
    ("remover_categoria", {"categoria": "Transporte", "valor": None}),
    ("remover_lembrete", {"descricao": "aluguel"}),
])
def test_erro_do_supabase_na_remocao_vira_problema_tecnico(banco, monkeypatch, tipo, extra):
    interpretar_como(monkeypatch, {"tipo": tipo, **extra})
    original = banco.__call__

    async def falha_na_remocao(req):
        if req.method == "DELETE" or "rpc" in req.url.path:
            return httpx.Response(500, json={"message": "erro"})
        return await original(req)

    monkeypatch.setattr(main, "_db", httpx.AsyncClient(transport=httpx.MockTransport(falha_na_remocao),
                                                       timeout=main.TIMEOUT_SUPABASE))
    r = post()
    assert r.status_code == 200
    assert "técnico" in r.text and "removido" not in r.text and "Não entendi" not in r.text
    assert len(banco.tabelas["gastos"]) == 3


def test_delete_levanta_em_erro_e_aceita_resposta_vazia(monkeypatch):
    monkeypatch.setattr(main, "_db", httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(403)),
                                                       timeout=main.TIMEOUT_SUPABASE))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(main.delete(f"{main.SUPABASE_API}/gastos", {"id": "eq.1"}))
    monkeypatch.setattr(main, "_db", httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(204)),
                                                       timeout=main.TIMEOUT_SUPABASE))
    assert asyncio.run(main.delete(f"{main.SUPABASE_API}/gastos", {"id": "eq.1"})) == []
