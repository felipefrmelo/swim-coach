# ADR-0012 — exclusão direta de treino em todas as superfícies

- **Status:** Accepted
- **Data:** 2026-08-26
- **Complementa:** ADR-0011

## Contexto

O produto pessoal precisa excluir um treino planejado pelo ChatGPT ou pela PWA
sem reintroduzir proposal, hash e aprovação. A exclusão pode tocar o calendário
local, o calendário Garmin e a biblioteca de treinos Garmin. A API Garmin pode
falhar depois que a remoção local já foi solicitada.

## Decisão

Adicionar `delete_workout` como a nona tool MCP, usando o mesmo scope `coach` e
annotations destrutivas/open-world para que o host apresente sua confirmação.
A PWA usa um único diálogo simples.

Ao aceitar a solicitação, o servidor remove a agenda local e move o treino para
o estado interno `deleting`, que não aparece em leituras. Um job idempotente,
serializado por treino com advisory lock, remove o agendamento e o template no
Garmin. Depois disso, revisões, binding e treino local são apagados fisicamente.
Falhas Garmin mantêm apenas o registro técnico oculto e são tentadas novamente.

Treinos `completed` ou ligados a uma atividade são protegidos. Atividades
registradas, inclusive no Garmin, nunca são excluídas por essa operação.

## Consequências

- a biblioteca e a agenda locais refletem a exclusão imediatamente;
- replay e `NOT_FOUND` do Garmin são sucesso idempotente;
- uma publicação concorrente não deixa órfão porque upsert e delete usam o mesmo lock;
- a limpeza Garmin pode aparecer como `QUEUED` ou `NEEDS_ATTENTION` sem restaurar o treino;
- não existe modo parcial nem seletor de destinos.
