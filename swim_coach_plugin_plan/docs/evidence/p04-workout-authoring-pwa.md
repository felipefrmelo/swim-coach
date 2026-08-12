# Evidência — P04 Treino canônico, calendário e editor PWA

## Resultado

O gate P04 foi demonstrado localmente em 2026-08-11: um usuário autenticado
criou pela PWA um treino canônico de 1.600 m para piscina de 20 m, aprovou a
revisão exata, agendou a sessão em `America/Sao_Paulo`, criou uma segunda
revisão e preservou o histórico. Nenhum caminho P04 importa ou recebe um
`GarminProvider`.

## Evidência funcional

- Playwright com Google Chrome, viewport 375×812: quatro fluxos P01/P02/P04
  passaram em 3,5 s, incluindo criação, aprovação, agenda, segunda revisão e
  rejeição visual de uma etapa de 50 m em piscina de 20 m.
- Captura sanitizada: [`p04-workout-editor-mobile.png`](p04-workout-editor-mobile.png).
- Stack Compose reconstruída: PostgreSQL, API, worker e PWA saudáveis; migration
  one-shot concluída.
- Consulta sanitizada ao PostgreSQL após o E2E: revision Alembic `000003`, quatro
  snapshots de revisão, duas agendas e oito eventos outbox P04. As repetições do
  E2E explicam hashes iguais entre execuções; nenhuma informação pessoal foi
  anexada.

## Evidência automatizada

- `make check`: Ruff e mypy em 67 módulos, 60 testes Python, ESLint, TypeScript,
  2 Vitest e validadores do repositório/plano verdes.
- Testcontainers: migration `000003` passou `up/down/up`, incluindo o trigger
  PostgreSQL que rejeita `UPDATE` em `workout_revision`.
- Testes de domínio/property: totais de repeats aninhados, múltiplos para
  comprimentos arbitrários, limites de profundidade/tamanho, hash canônico
  estável, ranges e snapshot frozen.
- Testes REST/PostgreSQL: draft inválido editável, aprovação somente de revisão
  válida/hash exato, ETag/`If-Match`, conflito de revisão e agenda com timezone.
- Contrato Draft 2020-12: fixture principal e os quatro exemplos de técnica,
  endurance, velocidade e teste validam no JSON Schema e terminam na parede.
- `make dependency-scan`: nenhuma vulnerabilidade conhecida em Python ou pnpm.
- `make secret-scan`: 9 commits e a árvore de trabalho sem vazamentos.
- GitHub Actions run `31551697015`: job `quality` verde em 1m29s em clone
  limpo do draft PR #4, incluindo testes, scans e build das imagens.

## Decisões e limites

- `definition_json` é a fonte canônica; totais e validação são snapshots
  derivados na mesma transação.
- Revisões são append-only na aplicação, frozen no domínio e protegidas contra
  `UPDATE` no banco; exclusão em cascata continua possível para privacidade.
- Editar uma revisão aprovada cria outra revisão e volta o agregado para draft;
  a agenda exige que a revisão corrente seja a aprovada.
- Aprovação e agenda são locais. P04 não compila payload Garmin e não causa
  qualquer efeito externo.
- A UI móvel seguiu a skill de design: alvos de toque de pelo menos 44 px,
  totais tabulares ao vivo, ações nomeadas, reordenação acessível e feedback
  visível sem depender de hover.

## Natureza dos dados

- Reais locais: PostgreSQL, browser, imagens Docker, API, migration, ETag,
  transações e arquivos gerados pela PWA.
- Fixtures sanitizadas: usuário `example.test`, piscinas, workouts e datas do
  E2E.
- Não executado/não alegado: publicação, agendamento ou leitura Garmin no fluxo
  P04; login Auth0 real; treino em dispositivo.
