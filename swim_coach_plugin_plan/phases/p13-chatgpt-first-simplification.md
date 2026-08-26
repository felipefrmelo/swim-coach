# P13 — ChatGPT-first e operação direta

## Objetivo

Substituir a UX baseada em proposals por uma superfície pessoal direta,
orientada a intenção, mantendo as garantias técnicas invisíveis.

## Dependências

- P00–P12 integradas na `main`;
- ADR-0011 aceita;
- Garmin e OAuth pessoais já conectados.

## Entregáveis

- contrato MCP v2 com oito tools e escopo `coach`;
- comandos diretos para salvar, editar, agendar, planejar, sincronizar e dar
  feedback;
- publicação Garmin idempotente sem proposal/hash no resultado público;
- PWA reduzida a calendário, editor e dois comandos: salvar; salvar e enviar;
- plugin/Skills 2.0 compatíveis apenas com a superfície v2;
- caminho legado não anunciado e sem dependência na UI;
- testes de contrato, integração, frontend e smoke de produção.

## Tasks

### P13-T01 — Fixar ADR e contratos públicos v2

Registrar os oito comandos, o scope `coach`, a compatibilidade legada e os
campos que deixam de ser públicos.

### P13-T02 — Implementar comandos diretos de treino

Criar/revisar/agendar com versão corrente gerenciada pelo servidor e sem
proposal/approval na interface.

### P13-T03 — Implementar Garmin upsert

Criar uma vez, atualizar o mesmo treino externo, mover a agenda e reconciliar
resultados ambíguos.

### P13-T04 — Publicar a superfície MCP de oito tools

Registrar schemas fechados, annotations corretas e o único scope `coach`.

### P13-T05 — Simplificar REST e PWA

Usar um comando de save com publicação opcional e remover a cerimônia visual.

### P13-T06 — Atualizar plugin, Skills e evals

Reescrever os sete workflows, validar, aplicar cachebuster e reinstalar o pacote
pessoal 2.0.

### P13-T07 — Isolar o legado e atualizar documentação

Desmontar rotas antigas no modo v2, remover canário e manter registros legados
somente para retenção/compatibilidade.

### P13-T08 — Validar e implantar

Executar checks completos, publicar, implantar API/worker/web, configurar Auth0
e comprovar o host em conversa nova.

## Gate

1. `tools/list` anuncia exatamente as oito tools privadas quando autenticado;
2. todas exigem somente `coach`;
3. criar/editar/agendar não retorna proposal, hash, approval ou idempotency key;
4. replay de publicação não cria duplicata;
5. edição publicada usa o binding Garmin existente;
6. PWA não contém ação de aprovar/revisar proposta;
7. plugin atualizado, validado, reinstalado e exercitado em conversa nova;
8. checks completos e deploy saudável na VM pessoal.

## Comandos de verificação

```bash
python tools/validate_plan.py
make check
make build
make dependency-scan
make secret-scan
```
