# Definition of Done

## Código

- [ ] implementação atende task/acceptance da fase;
- [ ] sem TODO crítico escondido;
- [ ] tipos e lint verdes;
- [ ] erros públicos catalogados;
- [ ] logs sanitizados;
- [ ] contratos atualizados quando necessário;
- [ ] documentação mínima no módulo.

## Testes

- [ ] unit tests de regras;
- [ ] integration tests quando há I/O;
- [ ] contract tests para API/MCP/provider;
- [ ] regressão para bug corrigido;
- [ ] testes negativos de auth/ownership;
- [ ] comandos e resultados registrados no status.

## Banco

- [ ] migration revisada;
- [ ] up/down/up testado quando aplicável;
- [ ] índices e constraints justificados;
- [ ] sem dados pessoais em seed;
- [ ] backfill idempotente.

## MCP/Plugin

- [ ] tool input/output schema válido;
- [ ] annotations corretas;
- [ ] resultado útil sem UI;
- [ ] scope e ownership testados;
- [ ] errors model-readable;
- [ ] Skill/evals atualizadas;
- [ ] nenhuma write silenciosa.

## Garmin

- [ ] provider adapter sem vazamento de tipo externo;
- [ ] fixture e smoke real quando possível;
- [ ] idempotência/reconcile;
- [ ] segredo protegido;
- [ ] feature flag para write.

## Segurança

- [ ] secret scan;
- [ ] threat model delta revisado;
- [ ] action hash/expiry/approval testados em writes;
- [ ] dados mínimos em output/log;
- [ ] dependências escaneadas.

## Operação

- [ ] health/metrics/logs;
- [ ] runbook para falha nova;
- [ ] retry seguro ou erro terminal explícito;
- [ ] rollback conhecido;
- [ ] status/changelog atualizados.

## Gate de fase

Uma fase é `DONE` apenas quando:

1. todos os critérios de aceite passam;
2. evidência real está registrada;
3. nenhuma dependência futura é simulada como pronta;
4. riscos bloqueadores foram resolvidos ou aceitos formalmente;
5. o próximo agente consegue executar a fase seguinte sem reconstruir contexto.
