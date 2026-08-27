# Catálogo de erros

Todos os erros públicos têm `code`, `message`, `correlation_id`, `retryable`, `details` sanitizado e, quando possível, `next_action`.

| Código | Categoria | Retry | Exposição |
|---|---|---:|---|
| `AUTH_REQUIRED` | auth | não | orientar login |
| `TOKEN_INVALID` | auth | não | não expor motivo criptográfico detalhado |
| `TOKEN_EXPIRED` | auth | após refresh | orientar reconexão |
| `SCOPE_REQUIRED` | authz | não | scope ausente pode ser informado |
| `ACCOUNT_DISABLED` | authz | não | genérico |
| `RESOURCE_NOT_FOUND` | domain | não | não revelar ownership |
| `OWNERSHIP_MISMATCH` | security/internal | não | mapear externamente para not found/forbidden |
| `VALIDATION_FAILED` | input/domain | não | field errors seguros |
| `POOL_DISTANCE_MISMATCH` | domain | não | informar múltiplo correto |
| `REVISION_CONFLICT` | concurrency | após refetch | revisão atual |
| `PROPOSAL_NOT_REVIEWABLE` | action | não | estado atual |
| `PROPOSAL_EXPIRED` | action | novo preview | expiração |
| `ACTION_HASH_MISMATCH` | security/action | novo preview | sem payload sensível |
| `APPROVAL_REQUIRED` | action | após confirmação | proposal id |
| `IDEMPOTENCY_CONFLICT` | concurrency | não | request hash difere |
| `JOB_ALREADY_RUNNING` | operation | acompanhar | job id |
| `JOB_NOT_RETRYABLE` | operation | não | estado/categoria |
| `PROVIDER_AUTH_FAILED` | Garmin | após reconnect | sem token/error raw |
| `PROVIDER_UNAVAILABLE` | Garmin | sim | backoff |
| `PROVIDER_RATE_LIMITED` | Garmin | sim | retry_after se seguro |
| `PROVIDER_SCHEMA_CHANGED` | Garmin | não automático | abrir incidente |
| `PROVIDER_AMBIGUOUS_RESULT` | Garmin | reconcile | não reenviar cegamente |
| `GARMIN_AUTH_REQUIRED` | Garmin/read | não | marcar conexão para reautenticação |
| `GARMIN_RATE_LIMITED` | Garmin/read | sim | backoff; não repetir em loop apertado |
| `GARMIN_NETWORK_ERROR` | Garmin/read | sim | backoff exponencial limitado |
| `GARMIN_NOT_FOUND` | Garmin/read | não | preservar cursor e diagnosticar |
| `GARMIN_SCHEMA_CHANGED` | Garmin/read | não automático | preservar payload sanitizado e corrigir adapter |
| `GARMIN_UNKNOWN_ERROR` | Garmin/read | não automático | somente código sanitizado e correlation id |
| `FIT_FILE_UNAVAILABLE` | data | sim/partial | activity id |
| `FIT_PARSE_FAILED` | data | após parser fix | checksum/parser version |
| `DATA_INCOMPLETE` | data | partial | campos ausentes |
| `STORAGE_UNAVAILABLE` | infra | sim | genérico |
| `DATABASE_UNAVAILABLE` | infra | sim | genérico |
| `SCHEMA_MISMATCH` | infra/release | após migration | revisão esperada sem SQL interno |
| `RATE_LIMITED` | abuse | após janela | retry-after limitado |
| `PAYLOAD_TOO_LARGE` | input | não | limite público configurado |
| `EXPORT_EXPIRED` | privacy | novo export | não revelar storage key |
| `DELETION_CONFIRMATION_MISMATCH` | privacy | frase exata | sem revelar ownership |
| `DELETION_STATE_CONFLICT` | privacy | refetch | estado sanitizado |
| `DELETION_NOT_DUE` | privacy | após cooling-off | instante devido |
| `WORKOUT_DELETE_COMPLETED_FORBIDDEN` | workout | não | atividade histórica vinculada é preservada |
| `WORKOUT_DELETE_STATE_CONFLICT` | workout/concurrency | após refetch | estado sanitizado |
| `INTERNAL_ERROR` | internal | talvez | somente correlation id |
