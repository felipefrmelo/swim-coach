# Convenções de nomes e versionamento

## Código

- Python modules/functions: `snake_case`;
- Python classes: `PascalCase`;
- TypeScript variables/functions: `camelCase`;
- DB: `snake_case` singular para tabela;
- MCP tools: `snake_case` orientado a verbo/objetivo;
- events: `swim_coach.<bounded_context>.<event>.v1`;
- error codes: `UPPER_SNAKE_CASE`;
- OAuth scopes: `resource:verb`;
- plugin/skills: `kebab-case`.

## IDs

- IDs internos UUID;
- prefixos somente em representação pública quando úteis (`job_`, `prop_`), sem mudar PK;
- external IDs sempre embrulhados em provider;
- logs usam hash/pseudônimo quando possível.

## Versões

- plugin: SemVer;
- Skill: versionada pelo plugin + content hash;
- MCP tool schema: major/minor explícito no contrato;
- JSON schema: `$id` + version;
- analysis/parser/ruleset: versões persistidas;
- API REST: `/api/v1` + compatibilidade aditiva;
- events: sufixo `.v1`.

## Units

- `*_m` distância;
- `*_seconds` duração;
- `*_seconds_per_100m` ritmo;
- `*_bpm` FC;
- timestamps ISO 8601 UTC;
- datas locais ISO `YYYY-MM-DD`;
- timezone IANA.

## Estados

Não usar booleanos para ciclos complexos. Enums canônicos estão em `contracts/state-machines.md` e no catálogo de erros/eventos.
