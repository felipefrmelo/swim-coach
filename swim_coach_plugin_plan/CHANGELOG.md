# Changelog

## [Unreleased]

### P00 — fundação executável

- criado workspace Python/TypeScript com lockfiles, comandos reproduzíveis e
  imagens Docker para API, worker e PWA;
- implementado MCP Streamable HTTP com um único tool público,
  `get_capabilities`, resultado estruturado e annotations read-only;
- criado plugin `0.0.0-spike`, marketplace local e Skill inofensivo; a cópia
  pessoal foi validada, instalada e habilitada no Codex;
- adicionada conexão MCP project-scoped do Codex, com allowlist exclusiva para
  `get_capabilities`, exercitada por sessão efêmera read-only do Codex;
- adicionados probes locais seguros para metadados OAuth/PKCE e leitura Garmin,
  sem obtenção ou impressão de tokens pelo probe OAuth e sem escrita Garmin;
- adicionados lint, typecheck, testes, validação de artefatos, auditoria de
  dependências, secret scan e CI com actions fixadas por SHA;
- corrigida vulnerabilidade reportada em `pytest 8.4.2` pela atualização para
  `pytest 9.1.1`;
- corrigidos os geradores/validadores do plano para ignorarem `.venv`,
  `node_modules`, builds e caches, evitando que dependências instaladas fossem
  interpretadas como documentos do plano;
- registrado handoff honesto: Auth0 real, Garmin real, conexão MCP HTTPS e CI
  remota ainda são necessários antes de concluir a P00.
- após três auditorias consecutivas sem os inputs externos necessários, alterado
  o checkpoint P00 de `IN_PROGRESS` para `BLOCKED`, sem liberar P01.
- corrigido o diagnóstico de GitHub após verificação fora do sandbox: `gh` está
  autenticado via keyring e o remote SSH está acessível; resta apenas autorização
  explícita para publicar as mudanças.

## [1.0.0-plan] — 2026-08-11

> Esta revisão publicou a especificação original antes da primeira implementação.

### Definido

- arquitetura **Plugin-first** como ponto de partida do produto;
- ChatGPT/Codex como interface conversacional principal;
- PWA com papel operacional, sem chat próprio no MVP;
- Skills para definir os workflows do treinador;
- MCP remoto como interface de dados, validações e ações controladas;
- UI MCP como melhoria opcional e portátil;
- plano modular em documentos, fases, prompts, contratos e ADRs;
- gates, status estruturado e protocolo de handoff para LLMs;
- objetos de plugin/MCP, invocação, proposta, aprovação e execução;
- OAuth 2.1 e escopos MCP;
- pacote de Skills e evals de seleção de ferramentas e segurança;
- blueprint de plugin pessoal;
- entrada explícita em [`LLM_START_HERE.md`](LLM_START_HERE.md);
- índice de tasks, índice de arquivos e matriz versionada de capacidades;
- exemplos canônicos e scripts de validação do plano;
- regra para gerar `.app.json` somente após registrar a conexão MCP real.

### Fora do escopo do MVP inicial

- chat próprio na PWA;
- chamada direta à OpenAI Responses API;
- armazenamento de conversas do host;
- tabelas `coach_conversation`, `coach_message`, `coach_run` e `ai_usage_record`;
- dependência de histórico conversacional como memória do treinador.

### Correções de consistência

- removida a documentação que tratava uma decisão de planejamento anterior como migração de produto;
- decisões descartadas foram tratadas como alternativas de planejamento, não como código ou dados legados;
- o modelo de dados agora descreve tabelas fora do escopo inicial, em vez de tabelas “removidas”.
