# ADR-0008 — Memória do treinador em dados estruturados

- **Status:** Accepted
- **Data:** 2026-08-05

## Contexto

O host mantém a conversa, mas decisões futuras precisam sobreviver a chats/modelos diferentes sem armazenar texto integral desnecessário.

## Decisão

Persistir fatos e decisões estruturadas: perfil, goals, feedback, analyses, `TrainingDecision`, `PlanningRun`, proposals e audit. Não persistir conversa do ChatGPT por padrão.

## Consequências

- privacidade e portabilidade melhores;
- o modelo precisa consultar tools;
- rationale deve ser estruturada no momento da decisão;
- sem “memória mágica” baseada em texto oculto.
