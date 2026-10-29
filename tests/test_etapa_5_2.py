"""Etapa 5.2: saída estruturada (união discriminada em Pydantic) em interpretar_mensagem.

Roda sem rede: o cliente da Anthropic e o Supabase são trocados por dublês.
"""
import asyncio
import json
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

# Uma resposta válida para cada uma das 16 intenções do SYSTEM_PROMPT.
INTENCOES = [
    {"tipo": "gasto", "descricao": "uber", "valor": 27.0, "categoria": "Transporte", "forma_pagamento": "não informado"},
    {"tipo": "receita", "descricao": "salário", "valor": 3000.0, "categoria": "Salário"},
    {"tipo": "relatorio", "periodo": "mes"},
    {"tipo": "relatorio_pagamento", "forma": "cartão", "periodo": "semana"},
    {"tipo": "saldo", "periodo": "hoje"},
    {"tipo": "comparativo"},
    {"tipo": "definir_meta", "categoria": "Alimentação", "limite": 500.0},
    {"tipo": "ver_metas"},
    {"tipo": "adicionar_lembrete", "descricao": "aluguel", "valor": 1200.0, "dia_vencimento": 5},
    {"tipo": "ver_lembretes"},
    {"tipo": "remover_lembrete", "descricao": "aluguel"},
    {"tipo": "remover_ultimo"},
    {"tipo": "remover_item", "descricao": "uber"},
    {"tipo": "remover_categoria", "categoria": "Lazer", "valor": None},
    {"tipo": "historico"},
    {"tipo": "ajuda"},
]


def resposta(texto, stop_reason="end_turn"):
    usage = SimpleNamespace(input_tokens=5, output_tokens=20,
                            cache_creation_input_tokens=0, cache_read_input_tokens=0)
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=texto)], usage=usage,
                           stop_reason=stop_reason)


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


def post(corpo="oi, tudo bem?", sid="SM1"):
    form = {"Body": corpo, "From": "whatsapp:+5511999999999", "MessageSid": sid}
    assinatura = RequestValidator("token-de-teste").compute_signature(URL, form)
    return TestClient(main.app).post("/webhook", data=form, headers={"X-Twilio-Signature": assinatura})


def test_a_lista_de_teste_cobre_as_16_intencoes_do_prompt():
    assert len({i["tipo"] for i in INTENCOES}) == 16
    for tipo in {i["tipo"] for i in INTENCOES}:
        assert f'"tipo": "{tipo}"' in main.SYSTEM_PROMPT


@pytest.mark.parametrize("esperado", INTENCOES, ids=lambda i: i["tipo"])
def test_intencao_valida_devolve_o_mesmo_dict(falso, esperado):
    falso.resp = resposta(json.dumps(esperado, ensure_ascii=False))
    assert asyncio.run(main.interpretar_mensagem("qualquer")) == esperado


def test_pedido_leva_o_schema_e_mantem_haiku_cache_e_sem_thinking(falso):
    asyncio.run(main.interpretar_mensagem("saldo de março"))
    pedido = falso.chamadas[0]
    assert pedido["output_config"] == {"format": {"type": "json_schema", "schema": main.SCHEMA_INTENCAO}}
    enviado = json.dumps(pedido["output_config"])
    assert "$defs" not in enviado and "$ref" not in enviado
    assert pedido["model"] == "claude-haiku-5-5"
    assert pedido["thinking"] == {"type": "disabled"}
    assert pedido["system"][0]["cache_control"] == {"type": "ephemeral"}


def percorre(no):
    if isinstance(no, dict):
        yield no
        for v in no.values():
            yield from percorre(v)
    elif isinstance(no, list):
        for v in no:
            yield from percorre(v)


def test_schema_enviado_so_usa_o_que_a_api_aceita():
    schema = main.SCHEMA_INTENCAO
    assert len(schema["anyOf"]) == 16  # oneOf do Pydantic virou anyOf
    nos = list(percorre(schema))
    # a API recusa `$defs` junto de `anyOf` (400); então tudo vai achatado dentro do anyOf
    for proibido in ("$defs", "$ref", "definitions", "oneOf", "discriminator", "const",
                     "minimum", "maximum", "default"):
        assert not any(proibido in n for n in nos), proibido
    objetos = [n for n in nos if n.get("type") == "object"]
    assert len(objetos) == 16
    for o in objetos:
        assert o["additionalProperties"] is False
        assert set(o["required"]) == set(o["properties"])  # nenhum parâmetro opcional
    # cada intenção fixa o seu `tipo` com um enum de um valor só
    tipos = {o["properties"]["tipo"]["enum"][0] for o in objetos}
    assert tipos == {i["tipo"] for i in INTENCOES}


@pytest.mark.parametrize("texto", [
    "não sei",                                                       # não é JSON
    "",                                                              # vazio
    '```json\n{"tipo": "ajuda"}\n```',                               # cerca de markdown não é mais aceita
    '["gasto"]',                                                     # JSON, mas não é objeto
    '{"valor": 10}',                                                 # sem tipo
    '{"tipo": "transferencia", "valor": 10}',                        # tipo desconhecido
    '{"tipo": "gasto", "descricao": "uber", "valor": 27.0}',         # faltam campos
    '{"tipo": "gasto", "descricao": "uber", "valor": "vinte", "categoria": "Outros", "forma_pagamento": "pix"}',
    '{"tipo": "saldo", "periodo": "ano"}',                           # fora do enum
    '{"tipo": "adicionar_lembrete", "descricao": "luz", "valor": 80.0, "dia_vencimento": 40}',
    '{"tipo": "remover_categoria", "categoria": "Lazer"}',           # `valor` é obrigatório (pode ser null)
])
def test_resposta_fora_do_schema_levanta_erro_de_interpretacao(falso, texto):
    falso.resp = resposta(texto)
    with pytest.raises(main.ErroInterpretacao):
        asyncio.run(main.interpretar_mensagem("???"))


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_recusa_ou_corte_levanta_erro_de_interpretacao(falso, stop_reason):
    falso.resp = resposta('{"tipo": "ajuda"}', stop_reason=stop_reason)
    with pytest.raises(main.ErroInterpretacao):
        asyncio.run(main.interpretar_mensagem("oi, tudo bem?"))


def test_campo_extra_e_descartado(falso):
    falso.resp = resposta('{"tipo": "saldo", "periodo": "mes", "extra": 1}')
    assert asyncio.run(main.interpretar_mensagem("saldo de março")) == {"tipo": "saldo", "periodo": "mes"}


@pytest.fixture
def webhook(falso, monkeypatch):
    monkeypatch.setattr(main, "registrar_mensagem", registro(True))
    return falso


@pytest.mark.parametrize("texto", [
    '{"tipo": "transferencia"}',
    '{"tipo": "gasto", "descricao": "uber"}',
    "texto solto",
])
def test_webhook_json_fora_do_schema_diz_nao_entendi(webhook, texto):
    webhook.resp = resposta(texto)
    r = post()
    assert r.status_code == 200
    assert "Não entendi" in r.text and "técnico" not in r.text


def test_webhook_com_resposta_valida_segue_o_fluxo_normal(webhook):
    webhook.resp = resposta('{"tipo": "ajuda"}')
    r = post("ajuda aqui")
    assert main.MENSAGEM_AJUDA.splitlines()[0] in r.text


def test_webhook_erro_da_anthropic_continua_sendo_problema_tecnico(webhook):
    webhook.erro = anthropic.APIConnectionError(request=httpx.Request("POST", "http://x"))
    r = post()
    assert "técnico" in r.text and "Não entendi" not in r.text
