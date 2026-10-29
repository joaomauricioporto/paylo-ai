# Plano — paylo-ai (etapas 5 e 6)

Uma etapa por sessão, sempre em uma branch. Ao terminar uma etapa, marque aqui e pare.

## Progresso

- [x] 5.1 SDK, modelo Haiku e cache do prompt (branch `etapa-5-1`, ver "Resultado da 5.1" abaixo)
- [x] 5.2 Saída estruturada (branch `etapa-5-2`, ver "Resultado da 5.2" abaixo; validada com a API real)
- [x] 6.3 Async com timeouts (branch `etapa-6-3`, ver "Resultado da 6.3" abaixo; validada com a API real)
- [x] 6.4 Corrida nas remoções (branch `etapa-6-4`, ver "Resultado da 6.4" abaixo; **falta rodar `sql/002_remover_ultimo.sql` no Supabase antes do merge**)
- [x] 6.1 Parser determinístico antes do modelo (branch `etapa-6-1`, ver "Resultado da 6.1" abaixo; **só merge depois de `scripts/comparar_parser.py` com zero divergências**)
- [ ] 6.2 Registro do tipo de intenção
- [ ] 6.5 Fila no webhook

Ordem sugerida: 5.1, 5.2, 6.3, 6.4, 6.1, 6.2, 6.5.

## Ajustes ao plano (leia antes de executar qualquer etapa)

O plano abaixo foi escrito sem ver o código. A realidade do repositório:

- Todo o código está em `main.py` (um único arquivo). Não existem `app/`, `services/`, `repositories/` nem `schemas/`. Onde o plano cita esses caminhos, faça a mudança dentro de `main.py`, e só crie um módulo novo se uma etapa pedir isso explicitamente.
- O webhook é `POST /webhook` (não `/webhook/twilio`).
- O Supabase é acessado por REST com `httpx` (helpers `get`, `post`, `delete` no topo do arquivo), sem a biblioteca `supabase-py`. Na etapa 6.3 use `httpx.AsyncClient`.
- Não existe tabela de mensagens com `user_id`. Existem `mensagens_processadas` (message_sid, telefone, criado_em) e as tabelas `gastos`, `receitas`, `metas`, `lembretes`, todas filtradas por `telefone`. Onde o plano diz `user_id`, use `telefone`.
- Migrações SQL vão em `sql/00N_nome.sql` (a próxima é a `002`). O João roda manualmente no Supabase; avise quando houver uma.
- Modelo atual: `claude-sonnet-4-6`. Antes de trocar para Haiku, confirme na documentação (docs.claude.com) o identificador atual (hoje `claude-haiku-5-5`) e o tamanho mínimo de prompt para cache nesse modelo. O system prompt do bot tem cerca de 1.100 tokens e pode ficar abaixo do mínimo do Haiku; nesse caso o cache não ativa. Meça `response.usage` e compare Haiku sem cache com Sonnet com cache em umas 30 mensagens reais antes de decidir.
- Etapa 5.2: confirme na documentação atual a forma recomendada de saída estruturada, sem presumir tool use com `strict`. Não crie o schema `intent_type/entities/reply_text/action_payload`. Mantenha o formato atual (campo `tipo` mais os campos de cada intenção) como união discriminada em Pydantic, para que o `if/elif` do webhook continue igual. A resposta ao usuário continua sendo montada pelo código, não pelo modelo. O `ValidationError` do Pydantic já cai no ramo "Não entendi".
- Etapa 6.1: o parser deve devolver o mesmo dict que `interpretar_mensagem` devolve hoje (`{"tipo": ..., ...}`), para o resto do fluxo não mudar.
- Etapa 6.2: em vez de nova tabela, acrescente `intent_type` e `parsed_by` em `mensagens_processadas` (migração `002`) e preencha depois da interpretação.
- Etapa 6.4: o helper `delete()` não verifica erro, e as remoções fazem SELECT e depois DELETE. Use `DELETE ... RETURNING` (no PostgREST, header `Prefer: return=representation`) e, para "remover último", uma função SQL (RPC) que apague e retorne a linha numa só instrução. Filtre sempre por `telefone`.
- Etapa 6.5: responder pela API REST da Twilio exige variáveis novas na Render (`TWILIO_ACCOUNT_SID` e o número remetente do WhatsApp), que o João precisa criar. Uma fila em memória perde mensagens se o serviço reiniciar ou dormir (plano gratuito da Render), e a idempotência já marca a mensagem como processada antes de tratá-la. Decida e documente como evitar que uma mensagem se perca sem resposta.

## Resultado da 5.1

- Conferido na documentação (platform.claude.com) em 2026-10-28: modelo `claude-haiku-5-5` (o atual; aposentadoria não antes de 07/10/2027); mínimo de cache **512 tokens** no Haiku 5.5 (4.096 no Haiku 4.5 e 1.024 no Sonnet 4.6). A suspeita do ajuste sobre o Haiku ficar abaixo do mínimo não se confirma: o prompt tem 2.311 caracteres (cerca de 700 a 900 tokens). Cache não exige header beta.
- Haiku 5.5 pensa por padrão. Por isso `interpretar_mensagem` manda `thinking={"type": "disabled"}` (aceito em esforço `high` ou menos; o padrão é `medium`) e lê o primeiro bloco de tipo `text`, não `content[0]`.
- `anthropic` foi de 0.49.0 para 2.3.0 (instala junto com `httpx==0.27.0`; o SDK usa `httpx2` por dentro). Timeouts ficam para a 6.3.
- O uso de tokens (`entrada`, `saída`, `cache_escrito`, `cache_lido`) agora aparece no log de cada mensagem.
- Testes: `tests/test_etapa_5_1.py` (pytest, sem rede). Requisição verificada com o SDK real contra um servidor local.
- **Decisão (2026-10-28): produção fica com Haiku 5.5 + cache.** Medido com chave real: o cache funcionou no Haiku (`cache_escrito` na 1ª chamada, `cache_lido` nas seguintes). Em 30 mensagens os dois modelos divergiram só em 1 ("comprei remédio 23 e 50": Haiku 23,50, Sonnet 73,00) e o Haiku acertou. O Sonnet 4.6 não cacheia com este prompt (899 tokens no tokenizer dele, mínimo 1.024; no Haiku 5.5 o prompt mede 1.247, mínimo 512), então seria mais caro e mais lento. Se o prompt crescer, lembre que o limite do Sonnet é outro.
- Comparação feita com `scripts/comparar_modelos.py` (resultado na decisão acima). A estimativa inicial de 700 a 900 tokens era para o Sonnet; o Haiku 5.5 conta mais tokens para o mesmo texto.

## Resultado da 5.2

- Conferido na documentação (platform.claude.com, structured outputs) em 2026-10-28: forma recomendada é `output_config={"format": {"type": "json_schema", "schema": ...}}` (o parâmetro antigo `output_format` está obsoleto em `create()`). `claude-haiku-5-5` está na lista de modelos aceitos. A doc **não diz** se funciona com `thinking` desativado, e o cache do system não é afetado enquanto o schema não mudar (mudar `output_config.format` invalida o cache); o `validar_schema.py` é quem confirma na prática.
- Schema: a doc lista `anyOf` como aceito e **não menciona `oneOf` nem `discriminator`**. O Pydantic gera `oneOf` + `discriminator`, então `main.py` converte: `anthropic.transform_schema` troca `oneOf` por `anyOf` e põe `additionalProperties: false`; antes disso `_simplificar_schema` tira o `discriminator` e troca `const` por `enum` (o SDK descarta `const` em silêncio). **1ª execução com chave real: 400 "For 'anyOf', '$defs' is not supported"** (a doc não menciona essa regra, a API sim). Correção: `_simplificar_schema` resolve todo `$ref` dentro do próprio `anyOf` e remove `$defs` (e os `title`), então o schema enviado não tem `$defs` nem `$ref`; teste sem rede garante isso. Limites da doc respeitados: nenhum parâmetro opcional (máx. 24) e só 1 parâmetro com união (`remover_categoria.valor`, máx. 16).
- Garantia de JSON puro: a doc diz que a decodificação é restrita pela gramática ("Always valid"), com exceções `refusal` e `max_tokens`. Por isso a limpeza de cercas de markdown saiu; `refusal` e `max_tokens` viram `ErroInterpretacao`. A doc avisa que a capitalização de `enum`/`const` não é garantida (em geral só a primeira letra após espaço; os valores daqui não têm espaço).
- `SYSTEM_PROMPT`: saiu só a linha "Responda APENAS com JSON válido, sem markdown" (a API já injeta a instrução do formato). Os exemplos de JSON ficam, pois documentam os campos. O prompt muda, então o cache é reescrito uma vez.
- `interpretar_mensagem` valida com `TypeAdapter` da união e devolve `model_dump()`, o mesmo dict de antes. Campos extras são descartados; campos faltando, tipo desconhecido, `periodo` fora de hoje/semana/mes e `dia_vencimento` fora de 1 a 31 levantam `ErroInterpretacao` ("Não entendi"). Categoria e forma de pagamento seguem texto livre, como antes.
- Testes: `tests/test_etapa_5_2.py` (sem rede). O teste da 5.1 sobre cerca de markdown foi trocado por um que garante que cerca levanta `ErroInterpretacao`. `pydantic==2.12.5` entrou em `requirements.txt` (já vinha pelo `fastapi`, agora está fixo).
- **Validação com a API real passou** (2026-10-28, `scripts/validar_schema.py`): schema aceito e 18 de 18 intenções batendo, com `thinking` desativado e cache no system. O cache com o schema tem 3.520 tokens. O plano B (objeto raiz com campo `intencao`) não foi preciso.

## Resultado da 6.3

- Tudo continua em `main.py`. Supabase: `httpx.AsyncClient` único (`db()`, criado no 1º uso e fechado no `lifespan`), com `httpx.Timeout(5.0, connect=3.0)` e, por cima, `asyncio.wait_for` de 5s por chamada (`requisitar`). Anthropic: `AsyncAnthropic` com timeout de 10s (conexão 3s). Toda função que toca a rede virou `async def`; `/` (health) segue síncrona por não fazer I/O.
- O SDK 2.3.0 usa `httpx2` e **recusa `httpx.Timeout`** (`TypeError`); por isso o timeout do cliente é `anthropic.Timeout`. O do Supabase continua `httpx.Timeout`.
- `max_retries=0` no cliente da Anthropic (o padrão do SDK são 2): a Twilio desiste em 15s, e um retry depois de 10s de timeout só estouraria o prazo. Se quiser retentativa para 429/529, o caminho é um prazo total, não só `max_retries`.
- Mapeamento de erros: `httpx.TimeoutException` e `anthropic.APITimeoutError` já eram subclasses de `httpx.HTTPError`/`anthropic.APIError`; o `asyncio.TimeoutError` do `wait_for` entrou na mesma cláusula de infraestrutura do `webhook`. Textos das respostas inalterados ("problema técnico" para infra, "Não entendi" para interpretação).
- Comportamento preservado de propósito: `delete()` continua sem checar erro (a 6.4 resolve) e as consultas seguem em sequência (nada de `gather` ainda). O `registrar_mensagem`, que tinha timeout de 10s, passou a usar os mesmos 5s do resto.
- Ainda não coberto: o webhook inteiro pode passar de 15s no pior caso (modelo 10s + várias chamadas de 5s). A 6.5 (fila) é quem resolve isso.
- Testes: `tests/test_etapa_6_3.py` (sem rede externa; timeouts verificados contra um servidor local que nunca responde; checagem por AST de que não sobrou chamada síncrona). Os testes da 5.1 e 5.2 foram adaptados (dublês `async`, `asyncio.run`).
- **Validação com a API real passou** (2026-10-29, `scripts/validar_async.py`: 15 mensagens pelo webhook + lote de 5 em paralelo; Supabase em memória, nada é gravado): 20 de 20 ok. Latência: 1,26s por mensagem em média (sequencial); o lote de 5 levou 1,56s contra 6,36s em fila, ou seja, as chamadas rodam de fato em paralelo. Uso nas 20 chamadas: entrada=250, saída=591, `cache_escrito=0`, `cache_lido=70.400` (3.520 por chamada, o prompt com o schema inteiro vindo do cache). O cache já estava aquecido por execuções anteriores, por isso nenhum `cache_escrito`.

## Resultado da 6.4

- `delete()` agora chama `raise_for_status()` (erro do Supabase cai no ramo "problema técnico") e devolve as linhas apagadas (`[]` se nada casou; resposta sem corpo também vira `[]`). O `HEADERS` global já trazia `Prefer: return=representation`, então o DELETE devolve a linha; o teste confere o header.
- `apagar_do_usuario(tabela, telefone, id)`: todo DELETE filtra por `id` **e** `telefone`; devolve a linha apagada ou `None`. `remover_gasto_por_descricao`, `remover_gasto_por_categoria` e `remover_lembrete` ainda fazem SELECT para achar o candidato (a busca é por texto), mas a resposta ao usuário vem do que o DELETE devolveu. Se outro processo apagou antes, volta `None` e o usuário vê "não encontrado" (mensagens de sempre).
- "Remover último": função SQL `remover_ultimo_gasto(p_telefone)` em `sql/002_remover_ultimo.sql`, chamada por `rpc()` (`POST /rest/v1/rpc/...`). Apaga e devolve numa instrução só, com `for update skip locked`: duas remoções simultâneas apagam dois gastos diferentes (o mais recente e o seguinte), nunca o mesmo duas vezes. Execução liberada só para `service_role`.
- Fora do escopo: `salvar_meta` ainda faz SELECT e depois PATCH/POST (outra corrida, não de remoção).
- Testes: `tests/test_etapa_6_4.py` (banco em memória atômico via `MockTransport`): remoção normal das 4 intenções, filtro por telefone, item inexistente, item que some entre SELECT e DELETE, duas remoções simultâneas (por `gather` e por duas requisições ao webhook) e erro 500 do Supabase. Os 11 testes que exercitam o comportamento novo falham no código antigo. Suíte completa: 74 passando.
- **Não testado:** a função SQL contra um Postgres de verdade (não há banco aqui); o teste usa um dublê da função. Rode-a no Supabase e teste no WhatsApp antes do merge.

---

# Plano original (Gemini)

---

## Resultado da 6.1

- `parse_deterministico(texto)` em `main.py`: normaliza (minúsculas, sem acento, espaços únicos) e só aceita frase inteira igual à lista; qualquer outra coisa devolve `None` e o modelo decide como antes. O resultado passa pelo mesmo `INTENCAO` do modelo, então o dict tem o mesmo formato.
- Coberto: ajuda (oi, ola, ajuda), saldo/quanto tenho/quanto sobrou (periodo `mes`), comparativo, ver_metas, ver_lembretes, historico (ultimos gastos), remover_ultimo (remover ultimo, desfazer) e definir_meta (`meta|limite|definir meta` + categoria da lista + número simples; `1.500` fica para o modelo).
- Fora de propósito: gasto, receita, relatórios, lembretes, remover_item/categoria (categoria, descrição e forma de pagamento dependem de julgamento do modelo).
- `interpretar_mensagem` chama o parser e só então `interpretar_com_modelo` (o código antigo, renomeado); o log diz `caminho=parser` ou `caminho=modelo`.
- Testes: `tests/test_etapa_6_1.py`. Os testes antigos que usavam "oi"/"saldo" para exercitar o modelo passaram a usar "oi, tudo bem?"/"saldo de março".
- Falta: rodar `scripts/comparar_parser.py` com chave real (zero divergências libera o merge).

## Etapa 5.1: Atualização do SDK Anthropic, Modelo Haiku e Prompt Caching

- **Objetivo:** Atualizar a biblioteca da Anthropic, migrar para o modelo Claude Haiku mais recente e ativar o cache do *system prompt* para reduzir latência e custos.
- **Arquivos e funções a mudar:**
  - `requirements.txt` ou `pyproject.toml`
  - `app/config.py` (constantes de modelo e headers)
  - `app/services/llm.py` -> funções `get_anthropic_client()` e `build_system_prompt()`
- **O que fazer:**
  1. Atualizar o pacote `anthropic` para a versão mais recente.
  2. Conferir na documentação atual da Anthropic o identificador exato do snapshot mais recente do Haiku (ex.: `claude-haiku-4-5-20251001` ou `claude-3-5-haiku-latest`) e atualizar na configuração.
  3. Reestruturar o *system prompt* de string simples para uma lista de blocos de conteúdo, adicionando `"cache_control": {"type": "ephemeral"}` no bloco estático de instruções e exemplos.
  4. Caso a versão do SDK ou recurso específico exija header de beta explícito (verifique na doc atual se já está na API GA ou se requer `betas=[...]` / `extra_headers`), configurá-lo na chamada do cliente.
- **Como testar:** Enviar duas requisições seguidas em ambiente local (com prompt acima do mínimo de tokens exigido pelo cache da Anthropic) e inspecionar o objeto `response.usage`.
- **Critério de pronto:** Na primeira chamada, `cache_creation_input_tokens > 0`; na segunda chamada idêntica, `cache_read_input_tokens > 0`.

---

## Etapa 5.2: Saída Estruturada (Structured Outputs)

- **Objetivo:** Garantir que a resposta do Claude obedeça estritamente a um schema Pydantic, eliminando falhas de *parsing* de JSON livre.
- **Arquivos e funções a mudar:**
  - `app/schemas/llm_output.py` (novo arquivo ou módulo de schemas existente)
  - `app/services/llm.py` -> função `analyze_message()` / `generate_response()`
- **O que fazer:**
  1. Definir um modelo Pydantic `PayloLLMResponse` contendo os campos esperados (ex.: `intent_type` como Enum, `entities`, `reply_text`, `action_payload`).
  2. Na chamada ao Claude, substituir a instrução textual de JSON pelo uso de saída estruturada suportado pelo SDK atualizado (ex.: *Tool Use* forçado com `tool_choice={"type": "tool", "name": "paylo_response"}` e `strict: True`, conferindo na documentação atual do SDK o parâmetro ou header de beta correspondente, se necessário).
  3. Validar o retorno instanciando diretamente `PayloLLMResponse.model_validate(tool_input)`.
- **Como testar:** Criar testes unitários com mensagens ambíguas e verificar se o retorno da função é sempre uma instância válida de `PayloLLMResponse`.
- **Critério de pronto:** Zero uso de `json.loads()` manual com *regex* sobre texto livre do modelo; 100% das respostas validadas via Pydantic.

---

## Etapa 6.1: Parser Determinístico Antes do Modelo (Fast-Path)

- **Objetivo:** Interceptar comandos simples, saudações ou padrões óbvios via código/regex antes de chamar a API da Anthropic, economizando tokens e tempo.
- **Arquivos e funções a mudar:**
  - `app/services/pre_parser.py` (novo arquivo)
  - `app/services/message_handler.py` -> função `process_incoming_message()`
- **O que fazer:**
  1. Criar a função `try_parse_deterministic(text: str) -> PayloLLMResponse | None`.
  2. Implementar regras exatas e expressões regulares para comandos frequentes e estruturados (ex.: "ajuda", "saldo", "listar", ou padrões claros de remoção/adição simples).
  3. No fluxo principal (`process_incoming_message`), chamar `try_parse_deterministic` antes do serviço de LLM. Se retornar um objeto válido, pular a chamada ao Claude.
- **Como testar:** Rodar uma suíte de testes unitários com 10 frases conhecidas fazendo *mock* do cliente Anthropic para garantir que ele não seja chamado nos casos previstos.
- **Critério de pronto:** Comandos mapeados respondem em menos de 50ms sem realizar chamadas externas à API da Anthropic.

---

## Etapa 6.2: Registro do Tipo de Intenção das Mensagens

- **Objetivo:** Persistir no Supabase a intenção classificada (tanto pelo parser rápido quanto pelo Haiku) para auditoria, métricas e contexto.
- **Arquivos e funções a mudar:**
  - Migração SQL no Supabase (`supabase/migrations/...`)
  - `app/repositories/messages.py` -> funções `save_message()` ou `update_message_status()`
  - `app/services/message_handler.py` -> função `process_incoming_message()`
- **O que fazer:**
  1. Adicionar as colunas `intent_type` (texto/enum, *nullable* ou com default `'unknown'`) e `parsed_by` (`'deterministic'` | `'llm'`) na tabela de mensagens no Supabase.
  2. Atualizar o repositório para receber `intent_type` e `parsed_by` ao registrar ou atualizar o processamento do `MessageSid`.
  3. Passar o valor extraído do `PayloLLMResponse.intent_type` para a camada de banco de dados.
- **Como testar:** Enviar uma mensagem que caia no parser e outra que vá para o LLM; consultar a tabela no Supabase.
- **Critério de pronto:** Ambas as mensagens aparecem no banco com `intent_type` preenchido corretamente e a origem (`parsed_by`) identificada.

---

## Etapa 6.3: Migração para Async com Timeouts Explícitos

- **Objetivo:** Evitar bloqueio do *event loop* do FastAPI durante chamadas de rede (Anthropic, Supabase, Twilio) e impedir que requisições penduradas travem os *workers*.
- **Arquivos e funções a mudar:**
  - `app/services/llm.py` -> trocar `Anthropic` por `AsyncAnthropic`
  - `app/repositories/supabase_client.py` e módulos de repositório -> usar `create_async_client` (ou `httpx.AsyncClient`)
  - `app/api/webhooks.py` -> rota do webhook Twilio
- **O que fazer:**
  1. Substituir o cliente síncrono da Anthropic por `AsyncAnthropic`, configurando `timeout=httpx.Timeout(10.0, connect=3.0)`.
  2. Migrar as chamadas do Supabase para o cliente assíncrono (`AsyncClient`), envolvendo as operações de rede em blocos `asyncio.wait_for(..., timeout=5.0)`.
  3. Converter toda a cadeia de funções (`webhook` -> `handler` -> `services`/`repositories`) para `async def` / `await`.
  4. Mapear `asyncio.TimeoutError` e `anthropic.APITimeoutError` para a hierarquia de erros existente.
- **Como testar:** Simular lentidão com `unittest.mock` (fazendo o cliente esperar 15s) e verificar se a aplicação levanta o erro de timeout tipado no tempo configurado.
- **Critério de pronto:** Nenhuma chamada de I/O de rede síncrona/bloqueante restante nas rotas `async def` do FastAPI; todos os clientes externos possuem timeout configurado.

---

## Etapa 6.4: Correção da Condição de Corrida nas Remoções

- **Objetivo:** Garantir que requisições concorrentes ou mensagens duplicadas para remover/cancelar um item não causem estado inconsistente, deleção dupla ou erro de índice.
- **Arquivos e funções a mudar:**
  - Migração SQL / RPC no Supabase
  - `app/repositories/items.py` (ou o repositório responsável pelas remoções no domínio do `paylo-ai`) -> função `remove_item()` / `delete_entry()`
- **O que fazer:**
  1. Substituir o padrão vulnerável de "buscar item no banco (`SELECT`) -> verificar se existe no Python -> deletar (`DELETE`)" por uma operação atômica única no PostgreSQL.
  2. Executar `DELETE FROM tabela WHERE id = :id AND user_id = :user_id RETURNING *` (ou `UPDATE ... SET deleted_at = NOW() WHERE id = :id AND deleted_at IS NULL RETURNING *`).
  3. Se a query retornar a linha afetada, a remoção ocorreu com sucesso; se retornar vazio, o item já havia sido removido por outra requisição concorrente — tratar de forma idempotente informando ao usuário de modo amigável.
- **Como testar:** Disparar duas corrotinas simultâneas com `asyncio.gather()` tentando remover o mesmo registro.
- **Critério de pronto:** Apenas uma corrotina executa a remoção efetiva (recebendo o registro via `RETURNING`), a segunda recebe retorno vazio e trata o caso sem levantar exceção não tratada nem corromper saldos/totais.

---

## Etapa 6.5: Desacoplamento com Fila Assíncrona no Webhook

- **Objetivo:** Responder ao webhook da Twilio imediatamente (evitando o timeout de 15s da Twilio) e processar o parser/LLM/banco em background com controle de ordem por usuário.
- **Arquivos e funções a mudar:**
  - `app/api/webhooks.py` -> endpoint `POST /webhook/twilio`
  - `app/workers/queue.py` (novo arquivo)
  - `app/services/twilio_sender.py` -> função para envio ativo via API REST da Twilio
- **O que fazer:**
  1. No endpoint do webhook, manter apenas: validação de assinatura Twilio, checagem rápida de idempotência (`MessageSid`) e enfileiramento do payload.
  2. Implementar uma fila (usando `asyncio.Queue` com workers no `lifespan` do FastAPI para deploy em processo único, ou Redis/ARQ para múltiplos containers) garantindo serialização por usuário (locks por `From` / `user_id` para evitar que duas mensagens seguidas do mesmo usuário sejam processadas fora de ordem).
  3. Retornar imediatamente um TwiML vazio (`<Response></Response>`) com HTTP 200 para a Twilio.
  4. O *worker* consome a fila, executa o fluxo completo (parser -> Haiku -> Supabase) e envia a resposta final ao usuário usando a API REST de mensagens da Twilio.
- **Como testar:** Enviar um POST para o webhook e medir o tempo de resposta HTTP; em seguida, disparar 3 mensagens seguidas do mesmo número e verificar a ordem de processamento nos logs.
- **Critério de pronto:** O endpoint `/webhook/twilio` responde HTTP 200 em menos de 300ms independentemente da latência do Claude, e as mensagens de um mesmo usuário são processadas em ordem estrita (FIFO).