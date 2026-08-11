# Changelog

## [Unreleased]

### P01 — domínio, persistência e identidade

- implementados value objects tipados, entidades e serviços transacionais para
  identidade, atleta, piscina, disponibilidade, metas, jobs, outbox, auditoria
  e idempotência;
- adicionados SQLAlchemy assíncrono, PostgreSQL e migration Alembic `000001`,
  com teste automático `up/down/up`, repositories em Testcontainers e seed
  idempotente do contexto 20 m / 2.000 m / 45 min;
- adotado BFF OIDC com Authorization Code + PKCE, nonce, allowlist, sessão e
  CSRF opacos armazenados somente como hash; `dev-auth` permanece restrito ao
  ambiente não produtivo;
- adicionados REST `/me`, pools, availability e goals com Problem Details,
  correlation ID, optimistic locking, ownership e respostas 404 seguras contra
  IDOR;
- criado shell PWA mobile-first com TanStack Query/Router, estados honestos,
  perfil, piscinas, disponibilidade e meta, sem chat e sem antecipar o editor
  de treinos do P04;
- adicionados property, contract, integration e Playwright E2E tests; o gate
  final passou com 39 testes Python, 2 web e 1 fluxo mobile em Chrome;
- adicionada ADR-0010 para a sessão BFF e atualizados os contratos OpenAPI e de
  eventos de domínio;
- resolvida a referência futura incompleta do `Settings` interno do MCP SDK no
  factory, eliminando o warning do Pydantic sem alterar a superfície P00;
- registrados screenshot sanitizado, schema estrutural, scans de dependências e
  segredos e handoff completo da fase;
- corrigidos índices/checksums para ignorarem caches do Hypothesis e artefatos
  temporários do Playwright.

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
- registradas as provas externas reais: leitura Garmin sem escrita, Auth0 com
  authorization code/PKCE S256/DCR e Secure MCP Tunnel invocado pelo ChatGPT;
- adicionado protected resource metadata configurável em
  `/.well-known/oauth-protected-resource`, fechado por padrão e restrito a um
  par issuer/resource completo, com issuer HTTPS e exceção de resource HTTP
  limitada a loopback fora de produção;
- reduzido o bloqueio da P00 à revalidação do resource metadata/audience pelo
  tunnel após a nova rota;
- alinhado o discovery à rota path-aware esperada para o MCP `/mcp`, mantendo a
  rota raiz como compatibilidade e permitindo HTTP somente em loopback de
  desenvolvimento;
- concluída a revalidação OAuth contra Auth0 real: `tunnel-client doctor`
  encontrou o metadata com HTTP 200 e o probe completo confirmou
  `resource_binding=true`; P00 passou para `DONE` e P01 tornou-se elegível;
- após três auditorias consecutivas sem os inputs externos necessários, alterado
  o checkpoint P00 de `IN_PROGRESS` para `BLOCKED`, sem liberar P01.
- corrigido o diagnóstico de GitHub após verificação fora do sandbox: `gh` está
  autenticado via keyring e o remote SSH está acessível; resta apenas autorização
  explícita para publicar as mudanças.
- publicada a fundação no PR #1; GitHub Actions run `31515474864` concluiu o job
  `quality` verde em clone limpo, fechando P00-T08.

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
