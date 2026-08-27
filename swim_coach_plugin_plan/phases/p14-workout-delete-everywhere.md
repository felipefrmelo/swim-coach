# P14 — excluir treino em todos os lugares

## Objetivo

Permitir excluir um treino planejado pelo ChatGPT ou PWA com uma única ação,
removendo agenda local, agenda Garmin, template Garmin e persistência local.

## Dependências

- P13 implantada e exercitada;
- ADR-0012 aceita;
- provider Garmin de escrita ativo.

## Entregáveis

- estado interno `deleting` e migration `000011` reversível;
- job `workout.delete_everywhere` idempotente e serializado por treino;
- remoção segura de schedule/template Garmin com `NOT_FOUND` como sucesso;
- hard delete local após limpeza externa;
- nona tool `delete_workout`, REST `DELETE /workouts/{id}` e botão na PWA;
- Skill `delete-workout`, seis evals e plugin pessoal `2.1.0`.

## Tasks

### P14-T01 — Fixar ADR e contratos

Registrar semântica, proteção de atividades e annotations destrutivas.

### P14-T02 — Persistência e serviço de exclusão

Ocultar imediatamente, remover a agenda e enfileirar uma operação estável.

### P14-T03 — Provider e worker Garmin

Desagendar, excluir template, repetir falhas transitórias e concluir hard delete.

### P14-T04 — MCP, REST e PWA

Expor uma ação por superfície, sem protocolo público adicional.

### P14-T05 — Plugin, Skill e evals

Publicar a nona tool e o oitavo workflow pessoal na versão 2.1.

### P14-T06 — Testes e concorrência

Provar local-only, publicado, replay, retry, proteção de concluído e ownership.

### P14-T07 — Release e deploy

Validar, aplicar cachebuster, reinstalar e executar canário descartável real.

## Gate

1. leituras escondem `deleting` imediatamente;
2. um treino publicado some do calendário e da biblioteca Garmin;
3. replay e `NOT_FOUND` não duplicam efeitos;
4. concluído ou matched retorna conflito sem alteração;
5. MCP anuncia nove tools com apenas `coach`;
6. PWA oferece uma confirmação simples;
7. migration passa em up/down/up e checks ficam verdes;
8. release 2.1 é validada, instalada e implantada.
