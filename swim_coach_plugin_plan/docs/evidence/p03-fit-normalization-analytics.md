# P03 — evidência de FIT, normalização e analytics

Estado: implementação local concluída; comparação real dependente do P02.

## Escopo comprovado

- P03-T01: download isolado, extração ZIP segura, limite de 50 MiB, SHA-256,
  escrita atômica, permissões privadas e deduplicação do artefato;
- P03-T02: fixture JSON sintético, sanitizado, sem pessoa/dispositivo/local e com
  licença declarada no próprio arquivo;
- P03-T03/T04: Garmin FIT SDK oficial, CRC, parser/profile/input versionados,
  session/lap/length/record, fallback 20 m e replay que reutiliza a versão;
- P03-T05: pace/100 m, moving/elapsed/rest, SWOLF/strokes, CV, fade, volume,
  conclusão, sRPE, flags e qualidade/completude explícitas;
- P03-T06: match por data/distância/duração, confidence/source, correção manual
  auditada e exclusividade treino–atividade;
- P03-T07: RPE, técnica, fadiga, prazer, dor e nota com versão otimista; nenhuma
  interpretação ou diagnóstico médico;
- P03-T08: lista/detalhe móveis, séries, métricas, warnings, privacidade e feedback;
- P03-T09: golden, propriedades de fórmulas/unidades/zero, missing fields, storage,
  replay e FIT binário gerado pelo encoder oficial.

## Provas executadas

- `ruff check backend/src backend/tests tests` → verde;
- `mypy backend/src/swim_coach` → 83 arquivos, sem erros;
- `pytest backend/tests/unit/test_fit_parser.py -q` → 5 passed, incluindo CRC e
  round trip binário oficial;
- Testcontainers PostgreSQL → migration `000005` em `up/down/up` e pipeline de
  artifact/normalization/analysis/feedback/replay: 2 passed;
- `make check` → 87 Python + 2 Vitest, Ruff, mypy (83 arquivos), ESLint,
  TypeScript e validadores: verdes, sem warnings do plano;
- Playwright Chrome em 375×812 → 6 passed, incluindo detalhe/intervalos/feedback P03;
- dependency scan e gitleaks (14 commits + worktree) → nenhum achado;
- Compose build/up → migration aplicada e API, worker, web e PostgreSQL saudáveis;
  volume compartilhado confirmado como UID/GID `10001:10001`, modo `0700`.

O teste binário expôs e corrigiu uma falha real: `check_integrity()` consome o
stream do SDK. O parser agora cria um novo decoder para leitura após validar CRC.
O smoke Compose também expôs o volume inicialmente root-owned; dois init jobs
limitados aplicam posse e modo antes dos processos não-root. A repetição do E2E
P07 em banco persistente revelou uma colisão de marker entre revisões idênticas;
o marker passou a incluir a identidade da revisão e a suíte repetida ficou verde.

## Privacidade e segurança

- nenhum FIT real foi adicionado ao repositório;
- API retorna `raw_fit_exposed=false` e o teste confirma ausência de conteúdo,
  `storage_key` e `input_checksum`;
- worker registra somente ID do job e código sanitizado;
- caminho de storage rejeita absoluto/traversal e usa arquivo temporário + rename;
- ZIP aceita exatamente um `.fit`, sem traversal e dentro do limite descompactado.

## Limite honesto

O gate reproduzível por fixture está comprovado, mas a prova manual pedida pela
fase — atividade real mascarada e comparação de métricas com Garmin — depende do
bootstrap seguro e dos dois syncs idempotentes do P02. Até isso ocorrer, P03 fica
`IN_PROGRESS`. O adapter filesystem faz I/O síncrono pequeno e limitado dentro do
worker assíncrono; migrar para storage S3/MinIO ou thread pool dedicado antes de
escalar múltiplos workers.
