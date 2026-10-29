"""Etapa 6.1: parser determinístico antes do modelo. Sem rede: o cliente da Anthropic é um dublê."""
import asyncio
import logging
import os

os.environ["TWILIO_AUTH_TOKEN"] = "token-de-teste"
os.environ["ANTHROPIC_API_KEY"] = "chave-de-teste"
os.environ["SUPABASE_URL"] = "http://supabase.invalido"
os.environ["SUPABASE_KEY"] = "chave-de-teste"

import pytest
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator

import main

URL = "http://testserver/webhook"
TEL = "whatsapp:+5511999999999"

COBERTAS = [
    ("oi", {"tipo": "ajuda"}),
    ("Olá", {"tipo": "ajuda"}),
    ("  AJUDA  ", {"tipo": "ajuda"}),
    ("saldo", {"tipo": "saldo", "periodo": "mes"}),
    ("SALDO", {"tipo": "saldo", "periodo": "mes"}),
    ("quanto   tenho", {"tipo": "saldo", "periodo": "mes"}),
    ("comparar meses", {"tipo": "comparativo"}),
    ("Comparar  Meses", {"tipo": "comparativo"}),
    ("minhas metas", {"tipo": "ver_metas"}),
    ("meus lembretes", {"tipo": "ver_lembretes"}),
    ("últimos gastos", {"tipo": "historico"}),
    ("ULTIMOS GASTOS", {"tipo": "historico"}),
    ("desfazer", {"tipo": "remover_ultimo"}),
    ("remover último", {"tipo": "remover_ultimo"}),
    ("Remover ultimo", {"tipo": "remover_ultimo"}),
    ("meta lazer 300", {"tipo": "definir_meta", "categoria": "Lazer", "limite": 300.0}),
    ("Meta Alimentação 500", {"tipo": "definir_meta", "categoria": "Alimentação", "limite": 500.0}),
    ("limite saude 150,50", {"tipo": "definir_meta", "categoria": "Saúde", "limite": 150.5}),
]

AMBIGUAS = [
    "", "   ", "oi, tudo bem?", "saldo de março", "saldo hoje", "uber 27", "mercado 150 pix",
    "recebi salário 3000", "meta mercado 300", "meta lazer", "meta lazer 1.500", "meta lazer 300 reais",
    "meta lazer -5", "remover uber", "remover lazer", "remover lembrete aluguel", "desfazer o último",
    "lembrete aluguel 1200 dia 5", "comparar meses e metas", "metas lazer", "quanto gastei no cartão",
]


@pytest.mark.parametrize("texto,esperado", COBERTAS)
def test_parser_cobre_o_que_deve(texto, esperado):
    assert main.parse_deterministico(texto) == esperado


@pytest.mark.parametrize("texto", AMBIGUAS)
def test_parser_devolve_none_no_que_e_ambiguo(texto):
    assert main.parse_deterministico(texto) is None


def test_valor_da_meta_e_float_como_no_modelo():
    r = main.parse_deterministico("meta lazer 300")
    assert isinstance(r["limite"], float)


class ClienteQueNaoDeveSerChamado:
    def __init__(self):
        self.chamadas = 0
        self.messages = self

    async def create(self, **kwargs):
        self.chamadas += 1
        raise AssertionError("o modelo não deveria ser chamado")


@pytest.fixture
def sem_rede(monkeypatch):
    cliente = ClienteQueNaoDeveSerChamado()
    monkeypatch.setattr(main, "client", cliente)
    return cliente


def test_interpretar_usa_o_parser_sem_chamar_o_modelo(sem_rede, caplog):
    caplog.set_level(logging.INFO)
    assert asyncio.run(main.interpretar_mensagem("saldo")) == {"tipo": "saldo", "periodo": "mes"}
    assert sem_rede.chamadas == 0
    assert "caminho=parser" in caplog.text and "caminho=modelo" not in caplog.text


def test_interpretar_cai_no_modelo_quando_o_parser_devolve_none(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    chamadas = []

    async def modelo(mensagem):
        chamadas.append(mensagem)
        return {"tipo": "ajuda"}

    monkeypatch.setattr(main, "interpretar_com_modelo", modelo)
    assert asyncio.run(main.interpretar_mensagem("uber 27")) == {"tipo": "ajuda"}
    assert chamadas == ["uber 27"] and "caminho=modelo" in caplog.text


def post(corpo, sid="SM1"):
    form = {"Body": corpo, "From": TEL, "MessageSid": sid}
    assinatura = RequestValidator("token-de-teste").compute_signature(URL, form)
    return TestClient(main.app).post("/webhook", data=form, headers={"X-Twilio-Signature": assinatura})


def test_webhook_responde_comando_do_parser_sem_chamar_o_modelo(sem_rede, monkeypatch):
    async def registrar(sid, telefone):
        return True

    monkeypatch.setattr(main, "registrar_mensagem", registrar)
    r = post("oi")
    assert r.status_code == 200 and "Paylo" in r.text and sem_rede.chamadas == 0


def test_webhook_duplicata_continua_ignorada(sem_rede, monkeypatch):
    async def registrar(sid, telefone):
        return False

    monkeypatch.setattr(main, "registrar_mensagem", registrar)
    r = post("oi")
    assert r.text == main.TWIML_VAZIO and sem_rede.chamadas == 0


def test_webhook_mensagem_ambigua_vai_ao_modelo_e_erro_continua_problema_tecnico(sem_rede, monkeypatch):
    async def registrar(sid, telefone):
        return True

    monkeypatch.setattr(main, "registrar_mensagem", registrar)
    r = post("uber 27")
    assert sem_rede.chamadas == 1 and "problema técnico" in r.text.lower()
