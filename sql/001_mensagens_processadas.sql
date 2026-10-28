-- Idempotência do webhook: guarda o MessageSid (único por mensagem da Twilio)
-- para ignorar reenvios. Rode uma vez no SQL Editor do Supabase.
create table if not exists mensagens_processadas (
  message_sid text primary key,
  telefone    text not null,
  criado_em   timestamptz default now()
);
