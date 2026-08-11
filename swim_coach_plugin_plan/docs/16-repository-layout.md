# Estrutura do repositório alvo

```text
swim-coach/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── uv.lock
├── package.json
├── pnpm-lock.yaml
├── docker-compose.yml
├── .env.example
├── .github/workflows/
├── apps/
│   └── web/
│       ├── src/
│       │   ├── app/
│       │   ├── routes/
│       │   ├── features/
│       │   ├── components/
│       │   ├── api/
│       │   └── test/
│       └── public/
├── backend/
│   ├── alembic/
│   ├── scripts/
│   ├── src/swim_coach/
│   │   ├── bootstrap/
│   │   ├── domain/
│   │   │   ├── athlete/
│   │   │   ├── goals/
│   │   │   ├── workouts/
│   │   │   ├── activities/
│   │   │   ├── analytics/
│   │   │   ├── planning/
│   │   │   ├── actions/
│   │   │   └── shared/
│   │   ├── application/
│   │   │   ├── commands/
│   │   │   ├── queries/
│   │   │   ├── ports/
│   │   │   └── services/
│   │   ├── infrastructure/
│   │   │   ├── db/
│   │   │   ├── garmin/
│   │   │   ├── fit/
│   │   │   ├── storage/
│   │   │   ├── auth/
│   │   │   ├── jobs/
│   │   │   └── observability/
│   │   ├── interfaces/
│   │   │   ├── rest/
│   │   │   ├── mcp/
│   │   │   ├── worker/
│   │   │   └── cli/
│   │   └── settings.py
│   └── tests/
│       ├── unit/
│       ├── integration/
│       ├── contract/
│       └── fixtures/
├── plugins/
│   └── swim-coach/
│       ├── .codex-plugin/plugin.json
│       ├── skills/
│       ├── assets/
│       └── .app.json        # gerado/ignorado quando contém mapping de ambiente
├── .agents/plugins/marketplace.json
├── contracts/
│   ├── openapi/
│   ├── mcp/
│   └── jsonschema/
├── tests/
│   ├── e2e/
│   └── evals/
├── docs/
│   ├── architecture/
│   ├── adrs/
│   ├── runbooks/
│   └── privacy/
└── infra/
    ├── docker/
    ├── nginx/
    └── backup/
```

## Regras de dependência

- `domain` não importa `application`, `infrastructure` ou `interfaces`.
- `application` importa `domain` e define ports.
- `infrastructure` implementa ports.
- `interfaces` chamam application; não chamam repository diretamente.
- MCP handlers não duplicam service logic.
- frontend consome OpenAPI client gerado ou contrato tipado.
- plugin Skills não importam código do backend; dependem de nomes/contratos de tool.

## Módulos e owners

| Módulo | Entidades principais | Casos de uso |
|---|---|---|
| athlete | profile, pool, constraints | configure context |
| goals | goal, milestone, progress | goal management |
| workouts | planned/revision/steps/template | author/validate/schedule |
| activities | activity/interval/length/raw | import/normalize/match |
| analytics | analysis/metrics/baselines | analyze/progress |
| planning | plan/week/rules/decisions | propose/adapt |
| actions | proposal/approval/execution | preview/approve/execute |
| garmin | connection/sync/bindings | provider operations |
| plugin | principal/invocation/release | MCP tools/observability |
| operations | job/outbox/audit/export | reliability |

## Configuração

`settings.py` valida variáveis por ambiente. Não acessar `os.environ` fora do bootstrap. Feature flags ficam no serviço, não espalhadas por `if` arbitrários.
