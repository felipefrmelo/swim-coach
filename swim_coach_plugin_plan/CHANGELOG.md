# Changelog

## [Unreleased]

### P13 — ChatGPT-first e operação direta

- aceita a ADR-0011, que substitui a cerimônia pública de proposal/hash por
  comandos de intenção e segurança invisível;
- entregue a superfície de oito tools MCP sob o escopo `coach`, com comandos
  diretos e sem proposal/hash/approval no contrato público;
- criado `CoachCommandService`, geração semanal direta e `GarminUpsertService`;
  replay, edição e mudança de data preservam um único binding Garmin;
- removido o modo canário e isolado o router REST legado quando v2 está ativo;
- PWA reduzida a “Salvar” e “Salvar e enviar ao Garmin”;
- sete Skills e 42 evals atualizadas; plugin pessoal
  `2.0.0+codex.20260826113352` validado e reinstalado.

### P12 — hardening, privacidade e release pessoal `1.0.0` (candidate)

- entregues imagens non-root, overlay de produção read-only/cap-drop, readiness
  de banco/schema/storage, headers, rate/body limits e operação atrás de HTTPS;
- criado backup PostgreSQL+artefatos com AES-GCM, manifest/checksums, retenção e
  restore fail-closed; drill real isolado preservou login, atividade e treino;
- adicionadas exportação ZIP user-scoped e exclusão staged com confirmação,
  cooling-off, revogação/cancelamento e tombstone sem identificador;
- definidos alertas/runbooks, threat model, incident response, load smoke e
  assessment separado que proíbe publicação pública automática;
- backend/PWA/plugin elevados a `1.0.0`; manifesto verificável, SBOM e quatro
  imagens Trivy zero HIGH/CRITICAL acompanham 126 testes Python e 4 web;
- plugin pessoal validado e atualizado para `1.0.0+codex.20260812170215`;
- reconciliado o checkpoint do README com P12/1.0.0 e registrado o CI final
  `31621402450` verde antes da integração da pilha na `main`;
- promovido o PR #13 de draft empilhado para PR umbrella pronto contra `main`,
  preservando os gates operacionais abertos e o histórico linear P00–P12;
- integrado o PR umbrella #13 em `main` como `a81d30c`; o gate pós-merge
  `31624985510` passou e os PRs empilhados incorporados foram encerrados;
- fase permanece `IN_PROGRESS` até o smoke em conversa nova e os gates reais P11
  e anteriores fecharem; `1.0.0` continua release candidate pessoal.

### P11 — automações recuperáveis e PWA offline segura (provas pessoais pendentes)

- adicionado scheduler por fuso com dedupe para sync, proposta semanal somente
  revisável, lembretes de treino/feedback e retenção de jobs concluídos;
- criado inbox de notificações deduplicadas e tela de operações com queue age,
  estados terminais e retry apenas quando seguro, user-scoped e idempotente;
- entregue cache offline estreito para shell e leitura de treino, indicador stale
  e exclusão explícita de proposals/aprovação/publicação/agendamento;
- feedback offline usa IndexedDB, idempotency key estável, estado visual pendente
  e reconciliação ao recuperar a rede;
- migration `000009`, OpenAPI, runbook e testes de fuso/replay/dedupe/retention/
  política offline acompanham a implementação;
- fase permanece `IN_PROGRESS` até ciclo automático pessoal, screenshot offline
  no iPhone e métricas reais da fila serem capturados sem dados sensíveis.

### P10 — planejamento semanal adaptativo e plugin `0.4.0` (revisão real pendente)

- adicionados rulesets imutáveis/versionados, snapshots canônicos, planning runs
  idempotentes e decisões ordenadas com regra, evidência, antes/depois e motivo;
- criado gerador semanal determinístico com piscina/duração, teto de três sessões
  e 8% de progressão, recuperação, dor/RPE/aderência, spacing intenso e ausência
  explícita de rollover automático de treinos perdidos;
- entregue `propose_week_plan` com schema fechado, scopes próprios, ownership e
  resultado sempre como proposal revisável, sem criar/agendar/aprovar/executar;
- ampliado `get_goal_progress` para endurance, pace, consistency e confidence,
  sempre acompanhado por sample size e qualidade;
- migration `000008` adiciona `training_rule_set`, `planning_run` e
  `training_decision` e permite proposals de goal sem revisão fictícia de workout;
- plugin elevado a `0.4.0` com Skill `plan-swim-week`; dataset agora contém sete
  Skills e 154 evals, 22 por Skill, incluindo bypass, dor, auth e dados ausentes;
- golden hash, property tests e integração MCP/PostgreSQL provam determinismo,
  replay, isolamento e aprovação sem alteração da agenda nem efeito externo;
- fase permanece `IN_PROGRESS` até uma semana baseada em dados reais persistidos
  ser revisada humanamente no ChatGPT com decisão e hashes sanitizados.

### P09 — UI opcional MCP Apps e plugin `0.3.0` (smoke no host pendente)

- adicionados cinco resources `ui://` versionados e cinco render tools read-only
  para treino/semana, atividade, meta, proposal e sync;
- adotado `text/html;profile=mcp-app`, `_meta.ui.resourceUri`, CSP fechada e
  bridge MCP Apps `ui/*`/`tools/call`, com fallback por capability detection;
- mantidas as tools de dados/ação desacopladas da renderização e a superfície
  P08 exatamente igual quando `SWIM_COACH_MCP_UI_ENABLED=false`;
- proposal expirada ou inválida falha fechada, approve/reject usa proposal e hash
  persistidos, double-click é bloqueado e execução externa nunca parte do card;
- entregue template autocontido, sem fetch/token/HTML não confiável, com foco,
  labels, alvos de 44 px e layout móvel sem scroll horizontal;
- plugin elevado a `0.3.0`, preservando seis Skills e 132 evals;
- fase permanece `IN_PROGRESS` até screenshot e smoke sanitizado em um host real
  do ChatGPT; o bridge host de teste não é promovido como essa prova.

### P08 — MCP de escrita controlada e plugin `0.2.0` (smoke real pendente)

- adicionada flag independente `mcp_write_enabled`, fail-closed sem OAuth, e
  bundles granulares de leitura, escrita local, sync, proposal, aprovação e ação;
- registradas 12 tools P08 com schemas fechados, annotations de risco e ownership;
- separada aprovação de execução: approval persiste somente decisão/hash e a
  execução exige chamada posterior, proposal aprovada, scope dinâmico e idempotência;
- implementados sync idempotente, feedback idempotente, rascunho, proposals de
  mudança/reagendamento, preview Garmin, cancelamento e retry atômico apenas seguro;
- migration `000007` conecta invocação sanitizada a proposal/job por correlation
  e causation IDs, sem guardar argumentos livres ou credenciais;
- pacote atualizado para seis Skills e capability `Read` + `Write`; publicação
  contém proibição literal de preview/aprovação/execução no mesmo turno;
- adicionadas 66 evals P08, totalizando 132 casos com 22 por Skill, incluindo
  bypass, hash alterado, IDOR, auth, dados ausentes e follow-up explícito;
- integração provou hash adulterado, execução prematura, scope dinâmico, IDOR e
  replay com exatamente uma approval, execution e job; efeito ambíguo não é retentado;
- fase permanece `IN_PROGRESS` até upgrade/smoke em conversa nova, OAuth real e
  canário Garmin descartável confirmarem o gate fora de fixtures.

### P06 — plugin pessoal read-only `0.1.0` (smoke de instalação pendente)

- substituído o Skill P00 por três workflows de objetivo: revisão da última
  natação, progresso da meta e diagnóstico de sync somente leitura;
- criado manifesto `0.1.0` com capability exclusivamente `Read` e mapeamento
  `.app.json` para a conexão real já registrada, sem URL ou credencial fictícia;
- mantido o marketplace pessoal com instalação `ON_INSTALL` e release matrix
  impedindo Skills/tools de escrita antes da P08;
- adicionados metadados `agents/openai.yaml`, validação oficial de Skills/plugin,
  contratos estáticos e 66 evals de seleção, ordem, vazio, auth e adversarial;
- criado release candidate com hashes de manifesto, app mapping e Skills;
- removida flakiness do teste AES-GCM: a adulteração agora sempre altera um byte
  por XOR, em vez de ocasionalmente substituir `x` por `x` sem mudança;
- mantido `IN_PROGRESS`: a cópia pessoal continua no spike porque duas tentativas
  de upgrade fora do workspace expiraram na aprovação do ambiente; conversa nova
  e gate autenticado P05 ainda são provas manuais pendentes.

### P05 — MCP autenticado somente leitura (gate de host real pendente)

- implementado resource server OAuth com discovery OIDC, JWKS em cache/rotação,
  JWT RS256, issuer, audience/resource, validade, tipo, subject e scopes por tool;
- adicionadas oito tools MCP user-scoped para contexto, treinos, atividades,
  progresso e sync status, sem tool de write, sync remoto ou chamada Garmin;
- criados DTOs mínimos, paginação/limites, truncamento, sanitização de texto,
  envelope/erros estáveis e server instructions read-only;
- adicionada migration `000006` para invocation sanitizada com hash dos argumentos,
  outcome e latência, sem bearer, FIT, e-mail ou texto livre;
- schemas fechados e annotations são comparados ao contrato versionado; cliente
  MCP cobre auth, scope, subject mapping, IDOR, invalid input e headless output;
- removidos N+1 de activities/analysis e workouts/schedules; reads medidos com
  duas queries para swims e até cinco para semana, p95 local abaixo de 500 ms;
- comprovados 91 testes Python, 2 Vitest e gate estático completo; a fase continua
  `IN_PROGRESS` até MCP Inspector e ChatGPT/Codex consultarem dados Garmin reais
  com token Auth0 user-scoped.

### P03 — FIT, normalização e analytics (comparação real pendente)

- adicionado storage privado atômico e deduplicado para artefatos FIT, com
  checksum, limite de tamanho, permissões restritas e volume Compose persistente;
- integrado o SDK oficial Garmin FIT com validação de CRC, parser versionado e
  normalização de session/lap/length/record para piscina de 20 m;
- criadas migration `000005`, versões imutáveis, laps, intervals, lengths,
  análises, matching inicial e feedback otimista/auditável;
- implementadas métricas determinísticas de ritmo, descanso, SWOLF, strokes,
  consistência, fade, volume, sRPE e qualidade explícita;
- entregue API user-scoped sem FIT/checksum/storage key e PWA móvel de lista,
  detalhe, séries e check-in sem diagnóstico;
- adicionados golden sanitizado, property tests, FIT binário oficial, replay,
  Testcontainers e E2E de UI por fixture;
- configurado bootstrap one-shot de posse/modo do volume FIT para manter API e
  worker sem root e os artefatos em `0700`;
- corrigido o marker externo P07 para ser único por revisão, preservando replay
  e evitando colisões entre treinos distintos com conteúdo idêntico;
- mantido `IN_PROGRESS` até a atividade real persistida do P02 permitir a
  comparação manual mascarada com as métricas Garmin.

### P07 — publicação Garmin pela PWA (gate real pendente)

- adicionados proposal/approval/execution/binding com hash canônico, expiração,
  optimistic locking, constraints e migration `000004`;
- implementado compilador determinístico e adapter Garmin de escrita isolado;
- criada revisão PWA de impacto com aprovação explícita e dois jobs idempotentes;
- resultados ambíguos agora são consultados externamente antes de qualquer retry;
- adicionados kill switch, flags read/write independentes e canário live obrigatório;
- provados 50 unitários, 14 integrações e E2E mobile fake; o gate permanece aberto
  até a única escrita real descartável ser confirmada sem duplicação;
- publicado o delta no draft PR #5, empilhado sobre o P04.

### P04 — treino canônico, calendário e editor PWA

- criado modelo canônico provider-neutral com steps/repeats discriminados,
  validação de parede, ranges, limites, totais recursivos e hash determinístico;
- adicionadas revisões append-only protegidas contra `UPDATE`, ETag/`If-Match`,
  aprovação local, templates e agenda IANA na migration `000003`;
- implementados REST e serviços user-scoped sem dependência Garmin;
- entregue editor PWA móvel com preset 1.600 m, reordenação acessível, repeats,
  totais ao vivo, erros/warnings, histórico e calendário semana/mês;
- adicionadas fixtures de técnica/endurance/velocidade/teste, property/contract/
  integration tests e quatro fluxos Playwright móveis;
- comprovados 60 testes Python, 2 Vitest, E2E Chrome, Compose saudável e scans
  de dependências/segredos limpos.

### P02 — Garmin somente leitura (em validação real)

- implementados provider Garmin isolado, DTOs internos e classificação
  sanitizada de autenticação, rede, rate limit, not found e schema drift;
- adicionados AES-256-GCM user-scoped com key version/rotação, bootstrap CLI
  com MFA sem token store em disco e revogação local auditada;
- criada migration Alembic `000002` para conexão, cursor, runs, payloads,
  imports e atividades, com repositories e ownership por usuário;
- implementados sync incremental paginado, janela de sobreposição, filtro de
  pool swimming, checksum SHA-256, replay idempotente e cursor fail-closed;
- adicionado job `garmin.sync_activities` com advisory lock, retry/backoff e
  tratamento explícito de 429 e reautenticação;
- adicionadas API autenticada e tela PWA mobile-first para status, dispositivos,
  sincronização e linha do tempo, sem campo de senha Garmin no navegador;
- testes de fixture, criptografia/tamper/rotação, migration, paginação/dedupe,
  rate limit/retry e desconexão estão verdes; o gate permanece aberto até o
  smoke persistente com atividade real e replay sem duplicação.
- publicado o delta no draft PR #3 com CI completo verde, mantendo o estado
  `IN_PROGRESS` até a evidência Garmin persistente.

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
  temporários do Playwright;
- publicado o delta P01 no PR #2, empilhado sobre o PR #1 enquanto a P00 aguarda
  merge, com o GitHub Actions run `31546007309` verde em clone limpo.

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
