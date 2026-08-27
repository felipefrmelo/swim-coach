# Evidência P14 — excluir treino em todos os lugares

## Implementação

- migration `000011` adiciona o estado técnico oculto `deleting`;
- `WorkoutDeletionService` remove a agenda local e cria um job idempotente;
- worker e Garmin provider desagendam e excluem o template antes do hard delete;
- advisory lock por treino serializa upsert e delete;
- MCP, REST e PWA compartilham a mesma operação direta;
- `completed` e workout ligado a atividade são protegidos.

## Validação local

- Ruff e mypy aprovados;
- TypeScript aprovado;
- `make check`: 132 testes Python e 4 testes web aprovados;
- migration PostgreSQL up/down/up aprovada;
- integração de save/publish/delete/replay/retry cobre remoção local e Garmin fake;
- treino concluído retorna conflito sem alterar agenda ou histórico;
- Skill `delete-workout` aprovada pelo validador oficial.

## Evidência externa

- plugin pessoal `2.1.0+codex.20260827020956` validado e reinstalado;
- produção responde `ready` em `https://swim-coach.ozix.com.br/health/ready`;
- banco de produção está no schema `000011`;
- imagem da API anuncia nove tools e apenas o scope OAuth `coach`;
- escrita Garmin está ativa em modo `live`;
- API, worker, web e PostgreSQL permaneceram com zero reinícios e sem erros
  recentes após a implantação;
- canário descartável real concluiu publicação e exclusão com os jobs em
  `SUCCEEDED`, removeu o treino local e não tentou excluir atividade registrada;
- nenhuma linha `deleting` nem revisão do canário permaneceu no banco.

Resultado exato do probe real:

```json
{"canary":"p14_garmin_delete","delete_job":"SUCCEEDED","local_workout_removed":true,"publish_job":"SUCCEEDED","recorded_activity_delete_attempted":false}
```
