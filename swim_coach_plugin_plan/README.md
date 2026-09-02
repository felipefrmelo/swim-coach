# Swim Coach

O Swim Coach é um treinador pessoal de natação integrado ao Garmin. O ChatGPT é
a interface principal do usuário: por meio do plugin e do MCP remoto, ele revisa
natações, acompanha metas, planeja e adapta semanas, salva e publica treinos,
sincroniza o Garmin, mantém ciclos adaptativos versionados, registra feedback e
exclui treinos planejados.

O Codex é usado para desenvolver, testar e manter o projeto. O site/PWA é um
painel auxiliar, sem chat próprio, para calendário, edição visual, configuração,
diagnóstico, exportação, administração da conta e contingência.

O backend e o PostgreSQL são as fontes de verdade. Skills orquestram os fluxos,
mas a conversa nunca armazena o estado canônico do atleta ou dos treinos.

## Arquitetura

```text
ChatGPT (interface principal)
  └── plugin Swim Coach
      ├── oito Skills
      └── MCP remoto com dezessete comandos
          ├── domínio e serviços de aplicação
          ├── PostgreSQL + worker
          └── Garmin Connect

Site/PWA (painel auxiliar)
  ├── calendário e editor visual
  ├── configurações e diagnóstico
  ├── exportação e administração da conta
  └── contingência operacional
```

O MCP expõe comandos de contexto, ciclos de treinamento, treinos, atividades,
Garmin e feedback sob o scope `coach`. Revisões de ciclo usam diff e hash com
aprovação explícita; publicação Garmin continua separada e idempotente.

## Estrutura ativa

| Caminho | Finalidade |
|---|---|
| `backend/` | API REST/MCP, domínio, persistência, worker e testes Python |
| `apps/web/` | painel auxiliar PWA |
| `plugins/swim-coach/` | plugin pessoal 3.0.0 e oito Skills ChatGPT-first |
| `contracts/` | schemas e contratos estruturados ativos |
| `tests/` | testes E2E e avaliações atuais do plugin |
| `ops/` | alertas operacionais |
| `docs/runbooks/` | runbook apontado pelos alertas |
| `tools/validate_repository.py` | validação local dos contratos ativos |

## Desenvolvimento

Requer Python 3.12, Node 24 com Corepack, `uv`, Docker e Docker Compose.

```bash
make bootstrap
make check
docker compose up --build --wait
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/google-chrome make e2e
```

A API fica em `http://127.0.0.1:18000`, o painel auxiliar em
`http://127.0.0.1:14173` e o PostgreSQL em `127.0.0.1:55432`. As portas e
credenciais são configuradas por variáveis descritas em `.env.example`.

Sem `SWIM_COACH_OAUTH_ISSUER` e `SWIM_COACH_OAUTH_RESOURCE`, o MCP falha fechado
e libera somente `get_capabilities`. A integração Garmin permanece protegida
pelos kill switches do servidor.

## Experiência principal

Depois de instalar ou atualizar o plugin, abra uma conversa nova no ChatGPT e
faça um smoke user-scoped: consulte o contexto, revise a natação mais recente e
liste os treinos planejados. Escritas e publicação Garmin só devem ser testadas
com objetos descartáveis e os controles de segurança ativos.

Use o site quando precisar de uma representação visual, configuração,
diagnóstico, exportação, administração da conta ou contingência. Novos fluxos
cotidianos devem ser projetados primeiro para o ChatGPT e não podem depender de
um chat próprio no site.
