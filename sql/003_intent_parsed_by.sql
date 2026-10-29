-- Etapa 6.2: registra o tipo de intenção e quem interpretou a mensagem.
-- Rodar à mão no SQL Editor do Supabase. Não mexe no RLS da tabela.
alter table mensagens_processadas add column if not exists intent_type text;
alter table mensagens_processadas add column if not exists parsed_by text;

do $$
begin
    if not exists (select 1 from pg_constraint where conname = 'mensagens_processadas_parsed_by_check') then
        alter table mensagens_processadas
            add constraint mensagens_processadas_parsed_by_check
            check (parsed_by in ('parser', 'modelo'));
    end if;
end $$;
