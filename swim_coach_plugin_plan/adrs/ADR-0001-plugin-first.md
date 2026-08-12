# ADR-0001 — Adotar arquitetura Plugin-first

- **Status:** Accepted
- **Data:** 2026-08-05

## Contexto

O produto precisa de uma interface conversacional com acesso a dados e ações, mas construir e manter um chat próprio duplicaria capacidades do ChatGPT/Codex e adicionaria custo, memória de conversa e segurança de modelo ao MVP.

## Decisão

Usar um plugin OpenAI como interface conversacional principal, composto por Skills e um MCP remoto. A PWA será operacional. Não usar OpenAI Responses API no caminho crítico do MVP.

## Consequências positivas

- voz/conversa/host já disponíveis;
- Skills versionam workflows;
- backend controla dados e ações;
- mesma integração pode funcionar em superfícies suportadas;
- menor código de UI conversacional.

## Consequências negativas

- disponibilidade depende de conta/superfície;
- UX varia por host;
- exige MCP/OAuth/plugin packaging;
- PWA continua necessária como fallback.

## Alternativas rejeitadas

- chat próprio com Responses API;
- somente PWA sem conversa;
- MCP sem Skills.
