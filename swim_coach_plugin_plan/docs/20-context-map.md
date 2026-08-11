# Mapa de contexto por fase

Este arquivo reduz o contexto que uma LLM precisa carregar. Leia sempre `AGENTS.md`, `MASTER_PLAN.md`, `IMPLEMENTATION_STATUS.md` e a fase atual; depois os itens abaixo.

| Fase | Documentos obrigatórios | ADRs | Contratos |
|---:|---|---|---|
| P00 | 01,08,13,15,16,19,21,23,24 | 0001,0002,0006,0007 | oauth-scopes, error-catalog, capability-release-matrix |
| P01 | 00,01,02,03,13,16,23 | 0002,0005,0007 | state-machines, domain-events |
| P02 | 02,03,05,13,14,17,23 | 0003,0005 | error-catalog, domain-events |
| P03 | 03,06,14,15,23 | 0003,0005 | domain-events |
| P04 | 02,03,04,12,15,23 | 0002,0004 | canonical-workout, openapi |
| P05 | 08,09,13,15,23,24 | 0001,0004,0007 | mcp-tools, oauth-scopes, error-catalog, capability-release-matrix |
| P06 | 08,09,10,15,19,21,23,24 | 0001 | mcp-tools, capability-release-matrix |
| P07 | 04,05,09,13,14,23 | 0003,0004,0005 | state-machines, domain-events |
| P08 | 08,09,10,13,15,23,24 | 0004,0007 | mcp-tools, oauth-scopes, capability-release-matrix |
| P09 | 09,11,13,15,23,24 | 0004,0009 | mcp-tools, capability-release-matrix |
| P10 | 02,06,07,09,17,23,24 | 0004,0008 | domain-events, state-machines, capability-release-matrix |
| P11 | 12,14,15,23 | 0005,0006 | openapi, domain-events |
| P12 | 13,14,15,17,18,19,21,22,23,24 | todos | todos |

Números de documento referem-se ao prefixo em `docs/`.

## Limite recomendado de contexto

- não carregar todos os arquivos de fases futuras;
- consultar `docs/02` apenas nas categorias afetadas;
- usar contracts como verdade serializável;
- ler ADR completa quando a decisão toca o código;
- abrir referência externa somente quando a fase exigir validação atual.
