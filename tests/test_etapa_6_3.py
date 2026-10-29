"""Etapa 6.3: async com timeouts explícitos.

Roda sem rede externa: o Supabase é um httpx.MockTransport e, para os timeouts, um servidor local
que aceita a conexão e nunca responde.
"""
import ast
import asyncio
import os
import socket
import threading
import time
from types import SimpleNamespace

os.environ["TWILIO_AUTH_TOKEN"] = "token-de-teste"
os.environ["ANTHROPIC_API_KEY"] = "chave-de-teste"
os.environ["SUPABASE_URL"] = "http://supabase.invalido"
os.environ["SUPABASE_KEY"] = "chave-de-teste"

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

import main

URL = "http://testserver/webhook"
VERBOS_SINCRONOS = {"get", "post", "put", "patch", "delete", "request", "stream"}


def post(corpo="oi", sid="SM1"):
    form = {"Body": corpo, "From": "whatsapp:+5511999999999", "MessageSid": sid}
    assinatura = RequestValidator("token-de-teste").compute_signature(URL, form)
    return TestClient(main.app).post("/webhook", data=form, headers={"X-Twilio-Signature": assinatura})


@pytest.fixture
def servidor_mudo():
    """Aceita conexões TCP e nunca responde. Devolve a URL base."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    srv.settimeout(0.2)
    abertas, parar = [], threading.Event()

    def aceitar():
        while not parar.is_set():
            try:
                abertas.append(srv.accept()[0])
            except OSError:
                pass

    t = threading.Thread(target=aceitar, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.getsockname()[1]}"
    parar.set()
    t.join()
    for c in abertas:
        c.close()
    srv.close()


@pytest.fixture(autouse=True)
def db_limpo(monkeypatch):
    monkeypatch.setattr(main, "_db", None)


def usar_supabase_falso(monkeypatch, handler):
    monkeypatch.setattr(main, "_db", httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                                       timeout=main.TIMEOUT_SUPABASE))


# ---------- configuração ----------

def test_clientes_sao_assincronos_e_tem_timeout_explicito():
    assert isinstance(main.client, anthropic.AsyncAnthropic)
    assert main.client.timeout.read == 10.0 and main.client.timeout.connect == 3.0
    assert main.client.max_retries == 0
    assert main.TIMEOUT_SUPABASE.read == 5.0 and main.TIMEOUT_SUPABASE.connect == 3.0
    assert isinstance(main.db(), httpx.AsyncClient)
    assert main.db().timeout == main.TIMEOUT_SUPABASE


def test_nenhuma_chamada_de_rede_sincrona_no_codigo():
    arvore = ast.parse(open(main.__file__, encoding="utf-8").read())
    for no in ast.walk(arvore):
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute) \
                and isinstance(no.func.value, ast.Name) and no.func.value.id == "httpx":
            assert no.func.attr not in VERBOS_SINCRONOS, f"httpx.{no.func.attr} síncrono na linha {no.lineno}"
            assert no.func.attr not in ("Client",), f"httpx.Client síncrono na linha {no.lineno}"
        if isinstance(no, ast.Attribute) and no.attr == "Anthropic" and getattr(no.value, "id", "") == "anthropic":
            raise AssertionError(f"anthropic.Anthropic síncrono na linha {no.lineno}")
    # função síncrona nunca chama as que fazem I/O (sem await ela receberia só uma corrotina)
    assincronas = {n.name for n in ast.walk(arvore) if isinstance(n, ast.AsyncFunctionDef)}
    for fn in (n for n in ast.walk(arvore) if isinstance(n, ast.FunctionDef)):
        chamadas = {c.func.id for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        assert not chamadas & assincronas, f"{fn.name} é síncrona e chama {chamadas & assincronas}"


# ---------- helpers do Supabase ----------

def test_get_post_delete_e_registro_falam_com_o_supabase(monkeypatch):
    vistos = []

    def handler(req):
        vistos.append(req)
        if req.method == "GET":
            return httpx.Response(200, json=[{"id": 1}])
        if req.method == "POST" and req.url.path.endswith("mensagens_processadas"):
            repetida = req.headers["prefer"] == "return=minimal" and len(vistos) > 4
            return httpx.Response(409 if repetida else 201)
        if req.method == "POST":
            return httpx.Response(201, json=[{"id": 7}])
        return httpx.Response(204)

    usar_supabase_falso(monkeypatch, handler)

    async def cenario():
        assert await main.get(f"{main.SUPABASE_API}/gastos", {"telefone": "eq.x"}) == [{"id": 1}]
        assert await main.post(f"{main.SUPABASE_API}/gastos", {"valor": 1}) == [{"id": 7}]
        await main.delete(f"{main.SUPABASE_API}/gastos", {"id": "eq.1"})
        assert await main.registrar_mensagem("SM1", "whatsapp:+1") is True
        assert await main.registrar_mensagem("SM1", "whatsapp:+1") is False  # 409 = reenvio

    asyncio.run(cenario())
    assert [r.method for r in vistos] == ["GET", "POST", "DELETE", "POST", "POST"]
    assert vistos[0].url.params["telefone"] == "eq.x"
    assert all(r.headers["apikey"] == main.SUPABASE_KEY for r in vistos)
    assert vistos[1].headers["prefer"] == "return=representation"
    assert vistos[3].headers["prefer"] == "return=minimal"


def test_erro_http_do_supabase_continua_levantando(monkeypatch):
    usar_supabase_falso(monkeypatch, lambda req: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(main.get(f"{main.SUPABASE_API}/gastos"))


def test_salvar_meta_atualiza_com_patch(monkeypatch):
    vistos = []

    def handler(req):
        vistos.append(req)
        if req.method == "GET":
            return httpx.Response(200, json=[{"id": 3, "categoria": "Lazer"}])
        return httpx.Response(204)

    usar_supabase_falso(monkeypatch, handler)
    assert asyncio.run(main.salvar_meta("whatsapp:+1", "lazer", 300.0)) == "atualizada"
    assert vistos[-1].method == "PATCH" and vistos[-1].url.params["id"] == "eq.3"


# ---------- timeouts ----------

def test_supabase_que_nao_responde_estoura_o_timeout_do_httpx(monkeypatch, servidor_mudo):
    monkeypatch.setattr(main, "_db", httpx.AsyncClient(timeout=httpx.Timeout(0.2, connect=0.2)))
    t0 = time.monotonic()
    with pytest.raises(httpx.TimeoutException):
        asyncio.run(main.get(servidor_mudo + "/rest/v1/gastos"))
    assert time.monotonic() - t0 < 2


def test_teto_por_chamada_do_supabase_vira_asyncio_timeout(monkeypatch, servidor_mudo):
    monkeypatch.setattr(main, "_db", httpx.AsyncClient(timeout=httpx.Timeout(30.0)))
    monkeypatch.setattr(main, "TEMPO_MAX_SUPABASE", 0.2)
    t0 = time.monotonic()
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(main.get(servidor_mudo + "/rest/v1/gastos"))
    assert time.monotonic() - t0 < 2


def test_anthropic_que_nao_responde_levanta_apitimeouterror(servidor_mudo, monkeypatch):
    lento = anthropic.AsyncAnthropic(api_key="x", base_url=servidor_mudo, max_retries=0,
                                     timeout=anthropic.Timeout(0.3, connect=0.3))
    monkeypatch.setattr(main, "client", lento)
    t0 = time.monotonic()
    with pytest.raises(anthropic.APITimeoutError):
        asyncio.run(main.interpretar_mensagem("saldo"))
    assert time.monotonic() - t0 < 3


@pytest.mark.parametrize("onde", ["supabase_httpx", "supabase_teto", "anthropic"])
def test_webhook_com_timeout_responde_problema_tecnico(onde, servidor_mudo, monkeypatch):
    monkeypatch.setattr(main, "SUPABASE_API", servidor_mudo + "/rest/v1")
    if onde == "supabase_httpx":
        monkeypatch.setattr(main, "_db", httpx.AsyncClient(timeout=httpx.Timeout(0.2, connect=0.2)))
    elif onde == "supabase_teto":
        monkeypatch.setattr(main, "_db", httpx.AsyncClient(timeout=httpx.Timeout(30.0)))
        monkeypatch.setattr(main, "TEMPO_MAX_SUPABASE", 0.2)
    else:
        async def registrar_mensagem(sid, telefone):
            return True
        monkeypatch.setattr(main, "registrar_mensagem", registrar_mensagem)
        monkeypatch.setattr(main, "client", anthropic.AsyncAnthropic(
            api_key="x", base_url=servidor_mudo, max_retries=0, timeout=anthropic.Timeout(0.3, connect=0.3)))
    t0 = time.monotonic()
    r = post()
    assert r.status_code == 200
    assert "técnico" in r.text and "Não entendi" not in r.text
    assert time.monotonic() - t0 < 3


def test_timeout_depois_da_interpretacao_tambem_e_problema_tecnico(monkeypatch):
    """Falha de rede no meio do fluxo (já passou pelo modelo): continua no ramo de infraestrutura."""
    async def registrar_mensagem(sid, telefone):
        return True

    async def create(**kwargs):
        usage = SimpleNamespace(input_tokens=1, output_tokens=1,
                                cache_creation_input_tokens=0, cache_read_input_tokens=0)
        texto = '{"tipo": "saldo", "periodo": "mes"}'
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=texto)], usage=usage,
                               stop_reason="end_turn")

    async def get(url, params=None):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(main, "registrar_mensagem", registrar_mensagem)
    monkeypatch.setattr(main, "client", SimpleNamespace(messages=SimpleNamespace(create=create)))
    monkeypatch.setattr(main, "get", get)
    r = post("saldo")
    assert "técnico" in r.text and "Não entendi" not in r.text


# ---------- não bloqueia o event loop ----------

def test_duas_interpretacoes_ao_mesmo_tempo_nao_se_serializam(monkeypatch):
    async def create(**kwargs):
        await asyncio.sleep(0.4)
        usage = SimpleNamespace(input_tokens=1, output_tokens=1,
                                cache_creation_input_tokens=0, cache_read_input_tokens=0)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text='{"tipo": "ajuda"}')],
                               usage=usage, stop_reason="end_turn")

    monkeypatch.setattr(main, "client", SimpleNamespace(messages=SimpleNamespace(create=create)))

    async def cenario():
        t0 = time.monotonic()
        await asyncio.gather(*(main.interpretar_mensagem("oi") for _ in range(4)))
        return time.monotonic() - t0

    assert asyncio.run(cenario()) < 0.4 * 4 * 0.6  # em série seriam 1,6s
