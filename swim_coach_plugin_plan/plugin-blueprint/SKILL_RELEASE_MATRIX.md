# Matriz de release dos Skills

`skill-library/` contém o **estado-alvo** dos sete workflows de produto. O manifesto do blueprint não aponta para essa pasta. A implementação deve criar o diretório ativo `skills/` da release usando somente os itens liberados abaixo.

| Release | Skills ativos | Fonte/variante | Observação |
|---|---|---|---|
| `0.0.0-spike` | `swim-coach-capabilities` | `release-skills/p00/` | sem dados pessoais; manifesto fornecido |
| `0.1.0` | `review-latest-swim`, `goal-progress`, `diagnose-sync` | biblioteca; `diagnose-sync` deve ser reduzido à variante read-only | nenhuma tool de write disponível |
| `0.2.0` | anteriores + `adapt-workout`, `publish-to-garmin`, `post-swim-checkin` | biblioteca; `diagnose-sync` passa à variante read-and-trigger | confirmação, scopes e idempotência obrigatórios |
| `0.4.0` | anteriores + `plan-swim-week` | biblioteca | depende do motor adaptativo P10 |

## Regra de montagem

1. comece de um diretório de release vazio;
2. copie somente os Skills habilitados pela matriz estruturada em `contracts/capability-release-matrix.yaml`;
3. ajuste `diagnose-sync` para a variante da release;
4. valide cada nome de tool citado contra o catálogo da mesma release;
5. gere o manifesto com `Read` ou `Read + Write` conforme o gate;
6. conecte o MCP real via fluxo oficial;
7. rode evals antes de instalar a versão.

Skills futuros não devem ser instalados apenas porque já existem na biblioteca. A CI deve falhar se uma Skill citar uma tool ausente da release.
