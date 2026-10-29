"""Etapa 6.2: intent_type e parsed_by em mensagens_processadas.

Sem rede: o Supabase é um httpx.MockTransport; o modelo é um dublê.
"""
import json
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


def assinado(corpo, sid):
    dados = {"Body": corpo, "From": TEL, "MessageSid": sid}
    return dados, {"X-Twilio-Signature": RequestValidator("token-de-teste").compute_signature(URL, dados)}


class Supabase:
    def __init__(self, patch_status=204):
        self.patch_status = patch_status
        self.patches = []

    def __call__(self, req):
        if req.method == "PATCH":
            self.patches.append((dict(req.url.params), json.loads(req.content)))
            return httpx.Response(self.patch_status, json={"message": "column does not exist"} if self.patch_status >= 400 else None)
        if req.method == "POST" and req.url.path.endswith("/mensagens_processadas"):
            return httpx.Response(201)
        if req.method == "GET":
            return httpx.Response(200, json=[])
        return httpx.Response(201, json=[{"id": 1}])


@pytest.fixture
def banco(monkeypatch):
    def instalar(patch_status=204):
        sb = Supabase(patch_status)
        monkeypatch.setattr(main, "_db", httpx.AsyncClient(transport=httpx.MockTransport(sb)))
        return sb
    return instalar


def enviar(client, texto, sid):
    dados, headers = assinado(texto, sid)
    return client.post("/webhook", data=dados, headers=headers)


def test_parser_registra_intent_e_origem(banco):
    sb = banco()
    with TestClient(main.app) as c:
        r = enviar(c, "ajuda", "SM1")
        assert r.status_code == 200
    assert sb.patches == [({"message_sid": "eq.SM1"}, {"intent_type": "ajuda", "parsed_by": "parser"})]


def test_modelo_registra_intent_e_origem(banco, monkeypatch):
    sb = banco()

    async def modelo(msg):
        return {"tipo": "ajuda"}
    monkeypatch.setattr(main, "interpretar_com_modelo", modelo)
    with TestClient(main.app) as c:
        enviar(c, "me explica o que você faz?", "SM2")
    assert sb.patches == [({"message_sid": "eq.SM2"}, {"intent_type": "ajuda", "parsed_by": "modelo"})]


def test_nao_entendi_registra_nao_entendido(banco, monkeypatch):
    sb = banco()

    async def modelo(msg):
        raise main.ErroInterpretacao("lixo")
    monkeypatch.setattr(main, "interpretar_com_modelo", modelo)
    with TestClient(main.app) as c:
        r = enviar(c, "asdkjh qwe", "SM3")
    assert "Não entendi" in r.text
    assert sb.patches == [({"message_sid": "eq.SM3"}, {"intent_type": "nao_entendido", "parsed_by": "modelo"})]


def test_falha_do_patch_nao_afeta_a_resposta(banco):
    sb = banco(patch_status=400)  # coluna inexistente
    with TestClient(main.app) as c:
        r = enviar(c, "ajuda", "SM4")
    assert r.status_code == 200
    assert "comandos" in r.text.lower() or "Gasto" in r.text or "gasto" in r.text
    assert len(sb.patches) == 1


def test_duplicata_nao_registra(banco, monkeypatch):
    sb = banco()

    async def duplicada(sid, tel):
        return False
    monkeypatch.setattr(main, "registrar_mensagem", duplicada)
    with TestClient(main.app) as c:
        enviar(c, "ajuda", "SM5")
    assert sb.patches == []
