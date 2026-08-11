# ADR-0009 — UI MCP é opcional e standards-first

- **Status:** Accepted
- **Data:** 2026-08-05

## Contexto

Cards melhoram revisão, mas podem reduzir portabilidade e atrasar o MVP.

## Decisão

Implementar UI apenas após tools headless estáveis; usar MCP Apps padrão primeiro; extensões do host são capability-checked. Todo resultado precisa continuar suficiente sem UI.

## Consequências

- maior portabilidade;
- algum trabalho duplicado em texto/visual;
- P09 pode ser omitida sem quebrar o produto.
