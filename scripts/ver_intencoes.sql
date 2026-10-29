-- Contagem de mensagens por intenção e origem nos últimos 7 dias (rodar no SQL Editor do Supabase).
select
    coalesce(intent_type, '(sem registro)') as intent_type,
    coalesce(parsed_by, '(sem registro)')   as parsed_by,
    count(*)                                as total
from mensagens_processadas
where criado_em >= now() - interval '7 days'
group by 1, 2
order by total desc;
