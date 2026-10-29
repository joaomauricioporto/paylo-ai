"""Etapa 5.1: modelo Haiku, system prompt com cache, uso logado e webhook intacto.

Roda sem rede: o cliente da Anthropic e o Supabase são trocados por dublês.
"""
import asyncio
import logging
import os
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


def registro(nova):
    async def registrar_mensagem(sid, telefone):
        return nova
    return registrar_mensagem


def resposta(texto, **uso):
    usage = SimpleNamespace(input_tokens=5, output_tokens=20,
                            cache_creation_input_tokens=0, cache_read_input_tokens=0)
    for k, v in uso.items():
        setattr(usage, k, v)
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=texto)], usage=usage)


class ClienteFalso:
    def __init__(self, resp=None, erro=None):
        self.chamadas = []
        self.resp, self.erro = resp, erro
        self.messages = SimpleNamespace(create=self.create)

    async def create(self, **kwargs):
        self.chamadas.append(kwargs)
        if self.erro:
            raise self.erro
        return self.resp


@pytest.fixture
def falso(monkeypatch):
    f = ClienteFalso(resposta('{"tipo": "ajuda"}'))
    monkeypatch.setattr(main, "client", f)
    return f


def post(corpo="oi", sid="SM1"):
    form = {"Body": corpo, "From": "whatsapp:+5511999999999", "MessageSid": sid}
    assinatura = RequestValidator("token-de-teste").compute_signature(URL, form)
    return TestClient(main.app).post("/webhook", data=form, headers={"X-Twilio-Signature": assinatura})


def test_pedido_usa_haiku_cache_e_sem_thinking(falso):
    assert asyncio.run(main.interpretar_mensagem("saldo")) == {"tipo": "ajuda"}
    pedido = falso.chamadas[0]
    assert pedido["model"] == "claude-haiku-5-5"
    assert pedido["thinking"] == {"type": "disabled"}
    bloco = pedido["system"][0]
    assert bloco["text"] == main.SYSTEM_PROMPT
    assert bloco["cache_control"] == {"type": "ephemeral"}
    assert "temperature" not in pedido  # Haiku 5.5 recusa amostragem fora do padrão


def test_uso_de_tokens_vai_para_o_log(falso, caplog):
    falso.resp = resposta('{"tipo": "ajuda"}', cache_creation_input_tokens=1100)
    with caplog.at_level(logging.INFO):
        asyncio.run(main.interpretar_mensagem("saldo"))
    assert "cache_escrito=1100" in caplog.text


def test_le_o_texto_mesmo_com_bloco_de_thinking_antes(falso):
    falso.resp.content.insert(0, SimpleNamespace(type="thinking", thinking=""))
    assert asyncio.run(main.interpretar_mensagem("oi")) == {"tipo": "ajuda"}


def test_json_em_cerca_de_markdown_levanta_erro_de_interpretacao(falso):
    # Desde a 5.2 a API devolve JSON puro, então a cerca de markdown deixou de ser aceita.
    falso.resp = resposta('```json\n{"tipo": "saldo", "periodo": "mes"}\n```')
    with pytest.raises(main.ErroInterpretacao):
        asyncio.run(main.interpretar_mensagem("saldo"))


def test_json_invalido_vira_erro_de_interpretacao(falso):
    falso.resp = resposta("não sei")
    with pytest.raises(main.ErroInterpretacao):
        asyncio.run(main.interpretar_mensagem("???"))


def test_webhook_assinatura_invalida_403(falso):
    r = TestClient(main.app).post("/webhook", data={"Body": "oi", "From": "x", "MessageSid": "S"},
                                  headers={"X-Twilio-Signature": "errada"})
    assert r.status_code == 403
    assert falso.chamadas == []


def test_webhook_duplicata_nao_chama_o_modelo(falso, monkeypatch):
    monkeypatch.setattr(main, "registrar_mensagem", registro(False))
    r = post()
    assert r.status_code == 200 and "<Response></Response>" in r.text
    assert falso.chamadas == []


def test_webhook_mensagem_nova_responde(falso, monkeypatch):
    monkeypatch.setattr(main, "registrar_mensagem", registro(True))
    r = post()
    assert r.status_code == 200 and "Message" in r.text
    assert len(falso.chamadas) == 1


def test_webhook_erro_de_interpretacao_diz_nao_entendi(falso, monkeypatch):
    monkeypatch.setattr(main, "registrar_mensagem", registro(True))
    falso.resp = resposta("lixo")
    assert "entendi" in post().text.lower()


def test_webhook_erro_da_anthropic_diz_problema_tecnico(falso, monkeypatch):
    monkeypatch.setattr(main, "registrar_mensagem", registro(True))
    falso.erro = anthropic.APIConnectionError(request=httpx.Request("POST", "http://x"))
    assert "técnico" in post().text.lower()
