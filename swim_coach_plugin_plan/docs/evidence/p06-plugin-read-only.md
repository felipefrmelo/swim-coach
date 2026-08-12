# P06 — evidência do plugin pessoal read-only

Estado: release candidate `0.1.0` validado; upgrade pessoal e smoke de host pendentes.

Publicação: commit [`4528e59`](https://github.com/felipefrmelo/swim-coach/commit/4528e593c26594b915e4d12baf26e350b0f3ae9e),
[draft PR #8](https://github.com/felipefrmelo/swim-coach/pull/8), correção de
teste flakey [`dfd68b3`](https://github.com/felipefrmelo/swim-coach/commit/dfd68b3)
e GitHub Actions
[run 31603753428](https://github.com/felipefrmelo/swim-coach/actions/runs/31603753428)
com `quality` aprovado em 1m33s.

## Escopo comprovado

- P06-T01: `contracts/capability-release-matrix.yaml` libera exatamente
  `review-latest-swim`, `goal-progress` e `diagnose-sync` em modo read-only;
- P06-T02: cada Skill possui frontmatter de intenção, ordem de tools, tratamento
  de empty/auth/stale, resposta pt-BR/headless e proibição explícita de writes;
- P06-T03: manifesto `0.1.0` anuncia apenas `Read`, três prompts reais e caminhos
  existentes, sem assets, URLs legais ou capabilities inventadas;
- P06-T04: `.app.json` reproduz o mapeamento criado pelo host para a conexão real
  `plugin_asdk_app_6a7b7fbeceec819196c168888a9494b6`; o arquivo não contém token;
- P06-T05: marketplace pessoal `personal` já aponta para
  `./plugins/swim-coach` com `AVAILABLE` e `ON_INSTALL`; a cópia instalada ainda
  é o spike porque a aprovação externa do upgrade expirou duas vezes;
- P06-T06: 66 casos validados pelo schema, 22 por Skill: 5 direct, 5 indirect,
  3 follow-up, 3 empty, 3 auth e 3 adversarial. Ordem é read-only e todos os
  11 tools não-read da matriz são proibidos nos casos adversariais;
- P06-T07: compatibilidade estática/headless e idioma foram cobertos; ativação em
  conversa nova permanece pendente;
- P06-T08: `releases/plugin-0.1.0.json` registra SemVer e SHA-256 de manifesto,
  app mapping e Skills. O registro é `release_candidate`, não release concluído.

## Provas executadas

- `validate_plugin.py plugins/swim-coach` → aprovado;
- `quick_validate.py` nos três Skills → aprovados;
- `pytest backend/tests/contract/test_plugin_release.py -q` → 3 aprovados;
- dataset `tests/evals/cases/p06-read-only.yaml` → 66 documentos YAML válidos;
- `make check` → Ruff, mypy, ESLint, TypeScript, 94 testes Python, 2 Vitest e
  validadores do repositório/plano aprovados;
- `make dependency-scan` → nenhuma vulnerabilidade conhecida em Python/pnpm;
- `make secret-scan` → 19 commits e worktree sem vazamentos;
- regressão CI: o teste substituía o último byte aleatório por `x`, que em
  1/256 dos casos já era `x`; XOR `0x01` agora garante adulteração e o run verde;
- mapeamento real comparado com a cópia remota criada pelo host em cache local;
- `codex plugin list` → `swim-coach@personal` instalado e habilitado no spike.

## Hashes do release candidate

- manifest: `54fe3d65230bff5ab1daf97832c289c0f8b8a18389654cb6ac8957e89e187e41`;
- app mapping: `c9a2762870f08690de4f94978addbedb2e05ec35215823d4773093c49909a7b9`;
- review Skill: `52b16d1f462a406a0442d391108fa302fc63e953d44c03cdbdf82f885e073e6b`;
- goal Skill: `94932eb3b558e71367d2ac08958d3ebbaee682dcfb6727934d66c1ba4aa3ac6e`;
- sync Skill: `2e0c52832988e91592086bd16e0101e5667ed84cab012c48d3eba8120c2ea5e0`.

## Fonte oficial revalidada

A estrutura e o fluxo seguem as páginas oficiais OpenAI de
[criação de Skills](https://developers.openai.com/plugins/build/skills) e
[empacotamento de plugins](https://developers.openai.com/plugins/build/plugins),
revalidadas em 2026-08-12.

## Limite honesto

P06 permanece `IN_PROGRESS`. Nenhuma movimentação ocorreu em
`/home/felipe/plugins/swim-coach`: o backup planejado não foi criado e a versão
instalada continua `0.0.0-spike`. A prova final requer instalar a cópia `0.1.0`,
reabrir o host e acionar os três Skills em conversa nova. As leituras privadas
também dependem do gate Auth0/dado real ainda aberto no P05.
