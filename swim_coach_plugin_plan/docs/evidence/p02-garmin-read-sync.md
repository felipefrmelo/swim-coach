# P02 — evidências parciais de Garmin read sync

- Execução: 2026-08-11, `America/Sao_Paulo`
- Estado: `IN_PROGRESS`
- Regra: fixtures, PostgreSQL real local e Garmin real são distinguidos. A fase
  não passa para `DONE` antes do import persistente real e do replay.

## Implementação coberta

| Task | Estado | Evidência atual |
|---|---|---|
| P02-T01 | concluída | porta/DTOs sem tipos externos; fixture sanitizada |
| P02-T02 | concluída | AES-256-GCM round-trip, adulteração, AAD, rotação e masking |
| P02-T03 | concluída | CLI login/MFA em memória, token cifrado e disconnect auditado |
| P02-T04 | concluída | migration `000002`, mappings e repositories PostgreSQL |
| P02-T05 | concluída | paginação, overlap, pool filter, checksum e replay idempotente |
| P02-T06 | concluída | job, advisory lock, 429/backoff e falha terminal de auth |
| P02-T07 | concluída | REST/PWA status, devices, sync, runs e atividades; sem senha no browser |
| P02-T08 | pendente | executar bootstrap + dois syncs contra a conta Garmin real |

## Automação validada

```text
pytest backend/tests/unit -q
  31 passed

pytest backend/tests/integration -q
  10 passed no gate final

pytest backend/tests/integration/test_garmin_sync.py -q
  1 passed

pytest backend/tests/integration/test_job_lease.py -q
  2 passed

ruff check backend/src backend/tests
  passed

mypy backend/src/swim_coach
  passed (62 source files)

pnpm check/lint/test/build
  TypeScript e ESLint passaram; 2 Vitest passaram; Vite build passou

make check
  49 testes Python e 2 Vitest passaram; validadores passaram

Playwright em Google Chrome, viewport 375×812
  2 fluxos passaram, incluindo a tela Garmin sem input de password
```

O teste PostgreSQL descartável aplica `upgrade head`, `downgrade base` e novo
`upgrade head`. O sync por fixture percorre duas páginas; a primeira execução
cria duas atividades e a segunda cria zero, registrando duas como `skipped`.
Existem apenas duas linhas em `activity` e duas em `raw_provider_payload` após o
replay. O worker agenda retry de 429 e termina erro de autenticação sem retry.
Cancelamento fecha o run como `cancelled` sem criar cursor; duas requisições
concorrentes com a mesma chave geram somente um job.

## Prova externa já existente

O probe P00 executado pelo usuário contra a Garmin real retornou 20 atividades,
6 nados em piscina e 2 dispositivos, com `external_write_performed=false`.
Isso comprova acesso read-only e compatibilidade básica, mas não substitui o
gate P02 porque ainda não atravessou a nova criptografia/persistência/cursor.

## Gate ainda aberto

Executar com segredo apenas no ambiente local:

1. subir PostgreSQL/API/worker/PWA com uma chave Garmin gerada localmente;
2. criar/reutilizar o principal PWA local;
3. executar a CLI `connect` no backend e fornecer login/MFA sem eco;
4. executar `sync-once` duas vezes;
5. registrar somente contagens, status, checksum/IDs mascarados e confirmar que
   o segundo run tem `created=0` e `skipped>=1`;
6. verificar que banco/logs não contêm password/token e que disconnect remove o
   segredo local.

Nenhum token, senha, e-mail real ou ID externo foi anexado a esta evidência.

Captura mobile sanitizada do estado pré-conexão:
[tela Garmin](p02-garmin-mobile.png).
