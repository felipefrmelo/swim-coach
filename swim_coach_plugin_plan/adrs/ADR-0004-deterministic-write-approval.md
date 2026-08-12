# ADR-0004 — Proposta, aprovação e execução determinísticas

- **Status:** Accepted
- **Data:** 2026-08-05

## Contexto

Publicar/reagendar no Garmin e alterar calendário são efeitos externos. Instruções ao modelo não são controle suficiente.

## Decisão

Separar:

1. preview/proposal persistida;
2. revisão humana do impacto;
3. approval para `action_hash` exato;
4. execução idempotente;
5. reconciliação em ambiguidade.

## Invariantes

- proposta expira;
- mudança invalida hash;
- approval não executa;
- execução revalida tudo;
- nenhum retry cego após efeito ambíguo;
- auditoria obrigatória.

## Consequências

Mais etapas e tabelas, mas segurança e rastreabilidade significativamente melhores.
