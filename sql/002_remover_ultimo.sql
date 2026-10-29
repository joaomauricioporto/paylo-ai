-- Etapa 6.4: "remover último" atômico. Escolhe o gasto mais recente do telefone e o apaga
-- numa só instrução, devolvendo a linha apagada (vazio se não havia nenhuma).
-- skip locked: se outra remoção já está apagando o mais recente, esta pega o próximo
-- em vez de esperar ou apagar o mesmo duas vezes.
-- Rode uma vez no SQL Editor do Supabase.
create or replace function remover_ultimo_gasto(p_telefone text)
returns setof gastos
language sql
set search_path = public
as $$
  delete from gastos
  where id = (
    select id from gastos
    where telefone = p_telefone
    order by id desc
    limit 1
    for update skip locked
  )
  returning *;
$$;

-- O bot usa a service_role; ninguém mais precisa chamar esta função pela API.
revoke execute on function remover_ultimo_gasto(text) from public, anon, authenticated;
grant execute on function remover_ultimo_gasto(text) to service_role;
