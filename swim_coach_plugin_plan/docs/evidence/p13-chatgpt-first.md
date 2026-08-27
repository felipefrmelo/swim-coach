# Evidência P13 — ChatGPT-first e comandos diretos

## Resultado

A superfície pública foi reduzida a oito ferramentas sob o scope `coach`:
`get_coach_context`, `get_workouts`, `get_swims`, `save_workout`,
`publish_workout`, `generate_week`, `sync_garmin` e `save_feedback`.

O transporte MCP autenticado comprovou listagem, metadata de segurança,
`save_workout`, leitura por data e `generate_week`. Esses comandos não criaram
registros de proposal, approval ou execution e não retornaram hashes internos.

## Garmin

A integração PostgreSQL com provider fake comprovou:

- primeira publicação cria um treino e um agendamento;
- replay não cria novo job nem efeito;
- edição atualiza o mesmo treino externo;
- mudança de data remove o agendamento anterior e cria o novo;
- existe um único `ExternalWorkoutBinding` para o treino;
- zero `ActionProposal`, `ActionApproval` e `ActionExecution` no fluxo v2.

## Plugin e PWA

- sete Skills validadas pelo `skill-creator` e reescritas para comandos diretos;
- plugin validado pelo `plugin-creator` e reinstalado como
  `2.0.0+codex.20260826113352` no marketplace pessoal;
- 42 casos P13 cobrem direct, indirect, follow-up, empty, auth e adversarial;
- editor PWA usa um `POST /api/v1/workouts/save` e dois botões: salvar; salvar e
  enviar ao Garmin;
- actions REST legadas não são montadas no modo v2 e não há modo canário.

## Verificações executadas

- `ruff` e `mypy` verdes;
- TypeScript e 4 testes Vitest verdes;
- 19 testes focados de contrato/unidade verdes antes do manifest 2.0;
- 2 integrações P13 com PostgreSQL/Testcontainers verdes em 13,31 s;
- `make check`: 130 testes Python, 4 Vitest, lint, tipos e validadores verdes;
- build Vite e das quatro imagens Compose verde;
- 9 testes Playwright verdes, incluindo salvar, revisar e enviar com Garmin fake;
- dependências sem vulnerabilidades conhecidas e Gitleaks sem vazamentos;
- SBOM gerado e Trivy com zero HIGH/CRITICAL nas quatro imagens após rebuild
  sem cache com as correções Alpine atuais;
- smoke público e de runtime em produção concluído; autenticação pelo host
  ChatGPT permanece como gate manual.

## Produção pessoal

- implementação publicada na `main` em `4bf2cec` e hotfix do worker em
  `0887f96`; CI `32966318411` e `32966938164` verdes;
- API, PostgreSQL, worker e web saudáveis na VM `201.54.11.232`;
- `https://swim-coach.ozix.com.br` retorna 200, login retorna 303 para Auth0 e
  `/mcp/` sem token retorna 401;
- protected-resource metadata pública anuncia somente `coach`;
- Auth0 aceitou uma autorização não interativa com `coach` e respondeu apenas
  `login_required`, sem `invalid_scope`;
- runtime da imagem: MCP v2, planejamento e Garmin write live ativos; exatamente
  as oito tools P13 registradas;
- API e worker com `RestartCount=0` e sem erros recentes após o hotfix;
- banco pessoal: 1 usuário, 1 conexão Garmin ativa, 2 dispositivos, 4 treinos e
  zero treinos com bindings Garmin duplicados.

## Refinamento do editor e do payload Garmin

Em 2026-08-26, o editor canônico passou a expor `target` e `instructions` em
etapas de topo e filhas de repeats. O fluxo coberto cria RPE 5–6 no aquecimento,
ritmo 1:40–1:50/100 m na série principal, grava notas, salva e remonta o editor
com os mesmos valores. Não houve mudança de schema REST, banco ou migration.

O compilador agora inclui, de forma determinística:

- `poolLength`, unidade métrica e distância estimada no topo do workout;
- unidade métrica preferida nas etapas por distância;
- `description` por etapa para as notas;
- `pace.zone` com os limites canônicos convertidos para m/s;
- `swim.instruction` para RPE e o intervalo original como texto conservador;
- fallback textual e warning quando a capability nativa estiver desabilitada.

Verificações do refinamento:

- 13 testes focados do compilador Garmin verdes;
- 91 testes unitários Python verdes;
- 142 testes Python verdes na suíte completa da árvore preparada para publicação;
- 9 testes Vitest verdes, incluindo criação, salvamento, remontagem, reorder de
  etapas sem ID e repeats aninhados;
- TypeScript, ESLint, Ruff, Mypy, build Vite e validadores do repositório verdes
  na mesma árvore limpa.

Em 2026-08-27, a validação autenticada consultou os tipos reais de target e
confirmou `pace.zone` como ID 6 e `swim.instruction` como ID 18. Um workout
descartável de 80 m foi criado e lido de volta com piscina de 20 m, distância
estimada, notas, RPE e ritmo preservados; depois foi excluído. A prova não tocou
agenda nem atividades registradas. O intervalo RPE continua também no texto por
ser mais informativo que a categoria nativa do Garmin.
Referências usadas: [round-trip de natação em piscina](https://github.com/pablo-albaladejo/kaiord/blob/main/test-fixtures/gcn/WorkoutSwimmingAllStrokesOutput.gcn),
[faixa real de ritmo](https://github.com/Taxuspt/garmin_mcp/issues/89) e
[round-trip das opções do editor Garmin](https://github.com/mrclmtll/garmin-coach-llm/blob/d4f4858988e1d49c79fa8b81755c94e9e79610a5/backend/app/schemas/workout.py#L170-L183),
[códigos observados em workouts](https://github.com/edwillys/garmin-scheduler/blob/ad51085953916c0566af8197cc779d44102ebb5b/src/garmin_scheduler/garmin_constants.py#L117-L127)
e [enumeração completa pública](https://github.com/llehouerou/go-garmin/blob/cbf5895e08bf32ea5510aabfd392c892055de2ab/service_workout.go#L226-L248).

## Limite

Uma conversa já aberta não recarrega Skills/MCP. Após reconexão OAuth, o smoke
final deve ser feito em conversa nova e sem criar treino descartável no Garmin
do usuário.
