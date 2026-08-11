# OAuth scopes

| Scope | Uso | Tools/endpoints | Risco |
|---|---|---|---|
| `profile:read` | perfil/piscina/disponibilidade | get_training_context | baixo |
| `goals:read` | metas/progresso | get_training_context, get_goal_progress | baixo |
| `workouts:read` | treinos e calendário | get_today_workout, get_week_plan | baixo |
| `activities:read` | atividades | list_recent_swims, get_swim_activity | médio |
| `analytics:read` | métricas derivadas | get_swim_activity, get_goal_progress | médio |
| `sync:read` | estado de sync | get_sync_status | baixo |
| `sync:run` | iniciar leitura Garmin | sync_garmin_activities | médio/open-world |
| `feedback:write` | feedback pós-treino | record_session_feedback | médio |
| `workouts:write` | rascunhos/revisões/propostas | create/propose tools | médio |
| `planning:write` | proposta de semana | propose_week_plan | médio |
| `garmin:publish` | criar/agendar no Garmin | preview + execute conforme action | alto/open-world |
| `proposals:read` | ler impacto/estado | get_action_proposal | baixo |
| `proposals:write` | criar/cancelar proposta | proposal tools | médio |
| `proposals:approve` | aprovar hash exato | approve_action_proposal | alto |
| `operations:read` | jobs/status | get_job_status | baixo |
| `operations:retry` | retry seguro | retry_failed_job | alto |
| `data:export` | exportar dados | PWA/admin futuro | alto |
| `data:delete` | excluir conta/dados | PWA apenas no MVP | crítico |

## Bundles sugeridos

### Read

`profile:read goals:read workouts:read activities:read analytics:read sync:read proposals:read operations:read`

### Coach write local

Read + `sync:run feedback:write workouts:write planning:write proposals:write`

### Garmin action

Coach write local + `garmin:publish proposals:approve`

Não pedir `data:delete` ao plugin no MVP.
