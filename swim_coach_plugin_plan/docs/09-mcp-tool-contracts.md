# Contratos das ferramentas MCP

## 1. Princípios

As ferramentas representam **casos de uso**, não CRUD nem tabelas. Na P13, a
superfície pública tem oito comandos e nenhum preview técnico. Reads e writes
continuam anotados corretamente, mas um pedido explícito para publicar chama
`publish_workout` diretamente. Toda resposta usa envelope estável.

Clientes não enviam hashes, números de versão, approval/execution IDs nem chaves
de idempotência. O servidor deriva e audita esses valores. `get_workouts` também
omite hashes internos.

```json
{
  "schema_version": "1.0",
  "request_id": "req_...",
  "status": "OK",
  "data": {},
  "warnings": [],
  "next_actions": [],
  "human_summary": "Resumo curto e fiel aos dados."
}
```

### Status

- `OK`
- `ACCEPTED`
- `PARTIAL`
- `NOT_FOUND`
- `NEEDS_INPUT`
- `NEEDS_AUTHORIZATION`
- `CONFLICT`
- `FAILED`

## 2. Tool catalog

### Read-only

| Tool | Objetivo | Scope | UI | Annotations |
|---|---|---|---|---|
| `get_capabilities` | informar capacidades/limites/versionamento | público/autenticado | não | readOnly=true, openWorld=false |
| `get_training_context` | perfil, meta, piscina, disponibilidade e estado atual | `profile:read goals:read` | não | readOnly=true |
| `get_today_workout` | treino de uma data, default hoje do usuário | `workouts:read` | workout card opcional | readOnly=true |
| `get_week_plan` | semana, status e totais | `workouts:read` | week card opcional | readOnly=true |
| `list_recent_swims` | listar atividades recentes resumidas | `activities:read` | lista opcional | readOnly=true |
| `get_swim_activity` | detalhe/análise de uma atividade | `activities:read analytics:read` | comparison card opcional | readOnly=true |
| `get_goal_progress` | progresso da meta e evidências | `goals:read analytics:read` | progress card opcional | readOnly=true |
| `get_sync_status` | conexão, última sync, jobs e staleness | `sync:read` | status card opcional | readOnly=true |
| `get_action_proposal` | conteúdo/impacto/estado de proposta | `proposals:read` | confirmation card opcional | readOnly=true |
| `get_job_status` | acompanhar job assíncrono | `operations:read` | não | readOnly=true |

### Local writes / external reads

| Tool | Efeito | Scope | Observação |
|---|---|---|---|
| `sync_garmin_activities` | enfileira leitura externa e escrita local | `sync:run` | não espera Garmin terminar; retorna job |
| `record_session_feedback` | grava feedback do usuário | `feedback:write` | valida RPE/dor; upsert controlado |

### Proposal tools

| Tool | Efeito local | Scope | Nunca faz |
|---|---|---|---|
| `create_workout_draft` | cria rascunho canônico validado | `workouts:write` | publicar no Garmin |
| `propose_week_plan` | cria proposta de semana | `planning:write` | aprovar automaticamente |
| `propose_workout_change` | cria nova revisão/proposta | `workouts:write` | alterar revisão publicada |
| `propose_workout_reschedule` | cria proposta de data | `workouts:write` | mexer em agenda externa |
| `preview_garmin_publish` | compila e cria proposal de publicação | `garmin:publish` | enviar ao Garmin |
| `cancel_action_proposal` | cancela proposta ainda executável | `proposals:write` | apagar histórico |

### Approval/execution

| Tool | Efeito | Scope | Pré-condições |
|---|---|---|---|
| `approve_action_proposal` | registra decisão para hash exato | `proposals:approve` | confirmação explícita; não expirada |
| `execute_approved_action` | enfileira execução | scope da ação | proposta aprovada, hash atual, idempotência |
| `retry_failed_job` | cria retry controlado | `operations:retry` | erro retryable e ownership |

## 3. Inputs normativos

### `get_today_workout`

```json
{
  "date": "2026-08-05",
  "include_steps": true,
  "include_publish_status": true
}
```

`date` é opcional; backend usa timezone do usuário, nunca timezone do host.

### `list_recent_swims`

```json
{
  "limit": 5,
  "before": null,
  "include_analysis_summary": true
}
```

### `get_swim_activity`

```json
{
  "activity_id": "uuid",
  "include_intervals": true,
  "include_lengths": false,
  "max_intervals": 50
}
```

### `record_session_feedback`

```json
{
  "activity_id": "uuid",
  "rpe": 7,
  "technique": "DEGRADED_AT_END",
  "pain": {"present": false},
  "notes": "Respiração perdeu ritmo nas últimas séries.",
  "idempotency_key": "feedback-activity-uuid-v1"
}
```

### `propose_workout_change`

```json
{
  "workout_id": "uuid",
  "expected_revision": 3,
  "change_request": {
    "available_duration_seconds": 1800,
    "preserve_objectives": ["TECHNIQUE"],
    "user_reason": "Só tenho 30 minutos"
  }
}
```

A ferramenta interpreta apenas campos estruturados; a Skill traduz linguagem natural.

### `preview_garmin_publish`

```json
{
  "workout_id": "uuid",
  "revision": 4,
  "schedule_date": "2026-08-07",
  "target_device_id": "uuid|null",
  "idempotency_key": "publish-workout-uuid-r4-2026-08-07"
}
```

### `approve_action_proposal`

```json
{
  "proposal_id": "uuid",
  "expected_action_hash": "sha256:...",
  "decision": "APPROVE",
  "confirmation_text": "Confirmo publicar o treino Técnica 1600 m em 07/08/2026."
}
```

A confirmação textual é auditável, mas não substitui autorização/host approval.

### `execute_approved_action`

```json
{
  "proposal_id": "uuid",
  "idempotency_key": "execute-proposal-uuid-v1"
}
```

## 4. Outputs por categoria

### Treino

```json
{
  "workout_id": "uuid",
  "revision": 4,
  "title": "Técnica 1.600 m",
  "scheduled_local": "2026-08-07T07:00:00-03:00",
  "pool_length_m": 20,
  "totals": {"distance_m": 1600, "estimated_active_seconds": 2200, "estimated_rest_seconds": 400},
  "steps": [],
  "state": "APPROVED",
  "garmin": {"publish_status": "NOT_PUBLISHED"},
  "content_hash": "sha256:..."
}
```

### Atividade

```json
{
  "activity_id": "uuid",
  "started_local": "2026-08-03T18:30:00-03:00",
  "distance_m": 2000,
  "moving_seconds": 2820,
  "pace_seconds_per_100m": 141.0,
  "pool_length_m": 20,
  "analysis": {
    "consistency_cv": 0.043,
    "fade_pct": 6.2,
    "swolf_avg": 46,
    "data_quality": "GOOD"
  },
  "match": {"planned_workout_id": "uuid", "confidence": 0.92},
  "feedback": null
}
```

### Proposta

```json
{
  "proposal_id": "uuid",
  "proposal_type": "GARMIN_PUBLISH",
  "status": "READY_FOR_REVIEW",
  "action_hash": "sha256:...",
  "expires_at": "2026-08-05T15:00:00Z",
  "subject": {"type": "WORKOUT_REVISION", "id": "uuid", "revision": 4},
  "impact": {
    "external_effects": ["CREATE_GARMIN_WORKOUT", "SCHEDULE_ON_2026-08-07"],
    "distance_m": 1600,
    "warnings": []
  },
  "required_confirmation": true
}
```

## 5. Erros

| Código | HTTP/MCP semântica | Retry | Exemplo |
|---|---|---:|---|
| `AUTH_REQUIRED` | needs authorization | não até login | token ausente |
| `SCOPE_REQUIRED` | forbidden | não | falta `garmin:publish` |
| `RESOURCE_NOT_FOUND` | not found | não | activity id inválido |
| `OWNERSHIP_MISMATCH` | not found/forbidden sanitizado | não | ID de outro usuário |
| `VALIDATION_FAILED` | invalid params | não | 50 m em piscina 20 m |
| `REVISION_CONFLICT` | conflict | após refresh | treino editado |
| `PROPOSAL_EXPIRED` | conflict | criar novo preview | aprovação antiga |
| `ACTION_HASH_MISMATCH` | conflict | revisar | conteúdo mudou |
| `PROVIDER_UNAVAILABLE` | failed | sim/backoff | Garmin indisponível |
| `PROVIDER_AMBIGUOUS_RESULT` | needs reconciliation | não automático | timeout após create |
| `JOB_ALREADY_RUNNING` | accepted/conflict | acompanhar | sync duplicada |
| `RATE_LIMITED` | retry later | sim | limite Garmin |
| `DATA_INCOMPLETE` | partial | talvez sync | FIT ausente |

## 6. Annotations e side effects

- `readOnlyHint=true` somente quando nenhuma persistência de negócio ocorre.
- `sync_garmin_activities` é `readOnlyHint=false`, `destructiveHint=false`, `openWorldHint=true`.
- proposal tools são writes locais, não destrutivos.
- publish/schedule são `openWorldHint=true` e requerem confirmação.
- cancel pode ter `destructiveHint=true` apenas se cancelar ação já aprovada; descrever claramente.

### Boundary de confirmação P08

- `preview_garmin_publish` persiste somente uma proposal revisável e nunca chama
  Garmin;
- `approve_action_proposal` persiste decisão/hash e retorna `APPROVED` sem criar
  execution/job;
- `execute_approved_action` é uma chamada posterior, recebe somente proposal ID
  e chave idempotente, revalida expiry/revisão/hash persistido e exige o scope
  dinâmico da ação além de `proposals:approve`;
- Skills não podem chamar preview e approval/execute no mesmo turno inicial,
  mesmo quando o usuário tenta pré-autorizar;
- replay retorna a execution/job existente e efeito ambíguo nunca recebe retry
  automático.

## 7. Versionamento

- tool name permanece estável dentro da major version;
- adicionar campo opcional é compatível;
- remover/renomear campo exige `v2` ou tool nova;
- `schema_version` em input/output quando contrato complexo;
- Skills declaram tool versions compatíveis;
- evals executam em cada release.

O catálogo serializável está em `contracts/mcp-tools.yaml`.
