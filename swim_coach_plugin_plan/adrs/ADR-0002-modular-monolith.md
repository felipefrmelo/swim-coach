# ADR-0002 — Monólito modular com worker separado

- **Status:** Accepted
- **Data:** 2026-08-05

## Contexto

Uso pessoal, baixa carga e domínio ainda evoluindo não justificam microsserviços.

## Decisão

Um backend Python modular atende REST e MCP; worker separado usa o mesmo pacote. PostgreSQL é fonte de verdade. Limites internos seguem domínio/aplicação/infra/interfaces.

## Consequências

- deploy e transações simples;
- reuso real entre REST/MCP/worker;
- menor observabilidade distribuída;
- requer disciplina de módulos;
- extração futura é possível por ports/events.
