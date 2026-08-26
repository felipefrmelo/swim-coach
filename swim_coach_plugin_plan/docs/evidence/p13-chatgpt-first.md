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

## Limite

Uma conversa já aberta não recarrega Skills/MCP. Após reconexão OAuth, o smoke
final deve ser feito em conversa nova e sem criar treino descartável no Garmin
do usuário.
