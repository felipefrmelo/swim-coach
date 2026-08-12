# P07 — publicação Garmin com aprovação explícita

Estado: implementação local concluída; gate externo real pendente.

## Implementado

- ActionProposal, ActionApproval, ActionExecution e ExternalWorkoutBinding com
  ownership, máquina de estados, expiração, optimistic locking e hashes;
- migration `000004` com constraints e unicidade de idempotência/bindings;
- compilador Garmin determinístico com limites de capability e warnings de
  rebaixamento explícitos;
- preview REST sem chamada externa e aprovação/rejeição vinculadas ao hash;
- PWA móvel com antes/depois, distância, data, dispositivo, efeitos, hashes,
  verbo explícito e linha do tempo;
- jobs separados de publish e schedule, binding persistido, outbox/auditoria;
- reconciliação por leitura após resultado ambíguo, sem retry cego;
- flags independentes de read/write, kill switch e restrição canário no modo live;
- cancel/delete remoto deliberadamente fora do MVP; o rollback é local e auditável.

## Provas locais

- Ruff e mypy: verdes em 73 arquivos de código;
- unitários: 50 passed;
- integração PostgreSQL/Testcontainers: 14 passed, incluindo migration up/down/up,
  aprovação, dois jobs, replay e resultados ambíguos;
- web: TypeScript, ESLint, 2 Vitest e build Vite verdes;
- Playwright Chrome 375×812: proposta → aprovação → publish fake → schedule fake →
  `SUCCEEDED` em 3,8 s;
- replay/ambiguidade: uma chamada de create e uma de schedule, ambas reconciliadas;
- `make check`: 75 testes Python e 2 web, validadores sem warnings/erros;
- dependency/secret scans: nenhum achado em 12 commits ou na árvore de trabalho;
- screenshot: `docs/evidence/p07-garmin-publish-mobile.png`.

Durante a repetição E2E, um ID sequencial do adapter fake colidiu após restart. O
teste expôs a fragilidade e o adapter passou a derivar IDs estáveis dos hashes;
a repetição com captura passou.

## Limite honesto

Nenhuma escrita Garmin real foi executada. A fase permanece `IN_PROGRESS` até o
usuário executar o canário descartável via PWA, confirmar uma única entrada na
biblioteca e calendário Garmin e provar que o replay não duplica. O procedimento
está em `docs/operations/p07-garmin-write-reconciliation.md`.
