# ADR-0005 — Jobs e outbox em PostgreSQL

- **Status:** Accepted
- **Data:** 2026-08-05

## Contexto

Sincronizações, parsing e Garmin write são assíncronos. RabbitMQ/Redis adicionariam operação sem necessidade inicial.

## Decisão

Usar tabelas `job` e `outbox_event`, leases com `FOR UPDATE SKIP LOCKED`, retry/backoff e dead/terminal states.

## Consequências

- atomicidade com dados de negócio;
- operação simples;
- throughput limitado, suficiente para uso pessoal;
- exige retention e monitoramento de queue age;
- mudança futura requer ADR e métricas.
