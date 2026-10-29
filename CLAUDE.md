# Paylo.IA (paylo-ai)

Assistente financeiro pessoal no WhatsApp. O usuário escreve em linguagem natural ("mercado 150 pix", "saldo", "meta lazer 300") e o bot registra e consulta gastos, receitas, metas e lembretes.

## Como funciona

`POST /webhook` (Twilio) → valida a assinatura → idempotência por `MessageSid` → Claude interpreta a mensagem e devolve JSON com um `tipo` (16 intenções, definidas em `SYSTEM_PROMPT`) → funções leem/gravam no Supabase via REST (`httpx`) → responde em TwiML.

## Arquivos

- `main.py`: todo o app FastAPI (helpers do Supabase, IA, relatórios, webhook).
- `requirements.txt`: dependências com versão fixa.
- `sql/`: migrações manuais, numeradas (`001_...sql`). São rodadas à mão no SQL Editor do Supabase, não automaticamente.

## Variáveis de ambiente (ficam na Render, nunca no código)

`ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY` (chave `service_role`), `TWILIO_AUTH_TOKEN`, `WEBHOOK_PUBLIC_URL` (opcional, só se a validação da assinatura falhar atrás do proxy).

Sem `TWILIO_AUTH_TOKEN` o webhook responde 403 de propósito. Para testar localmente use um token de teste e assine a requisição com `twilio.request_validator.RequestValidator`.

## Banco (Supabase, projeto `mono-bot`)

Tabelas: `gastos`, `receitas`, `metas`, `lembretes`, `mensagens_processadas`. Os dados são separados por `telefone` (número do WhatsApp). O bot usa a `service_role`, então o RLS deve ficar ligado em todas as tabelas. Plano gratuito: o projeto pausa sozinho se ficar parado.

## Rodar local

```
pip install -r requirements.txt
uvicorn main:app --reload
```

## Deploy

Render, serviço `mono-bot`. **Push na `main` faz deploy automático e vai ao ar para usuários reais.** Trabalhe em uma branch (`git checkout -b nome`) e só faça merge depois de testar.

## Regras

- Nunca commitar nem colar em chat chaves, tokens ou `.env`.
- Mudança de schema vira um novo arquivo em `sql/`, avisando o João para rodar no Supabase.
- Mensagens que o bot envia ao usuário são em português, com o estilo atual (emojis, `*negrito*` do WhatsApp).
- Erros de interpretação ("Não entendi") e de infraestrutura ("problema técnico") ficam separados em `webhook`; mantenha assim e use `logger.exception`.
- Testes em `tests/` (`pip install pytest` e `pytest tests`), sem rede, com dublês para Anthropic e Supabase. Ao mexer no webhook, teste com `fastapi.testclient` simulando assinatura, duplicata e erros.
- Gastar poucos tokens: leia só os arquivos e trechos necessários (`main.py` tem ~570 linhas) e faça uma etapa por sessão.

## Estado e próximos passos

Já feito: validação da assinatura da Twilio, escape do XML, idempotência por `MessageSid`, separação dos tipos de erro, restauração do Supabase, etapa 5.1 (Haiku 5.5 + cache do system prompt + SDK 2.3.0; medição com chave real pendente, ver `PLANO.md`).

O que falta está no `PLANO.md` (quando existir). Se não existir, a ordem sugerida é: (5.2) saída estruturada, (6) async com timeouts, corrida nas remoções, medir tipos de intenção, parser antes do modelo e fila.
