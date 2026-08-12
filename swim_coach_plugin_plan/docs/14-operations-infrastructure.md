# Automações, observabilidade e infraestrutura

## 1. Topologia de implantação

O MVP pessoal usa um monólito modular e poucos processos:

```text
Internet / ChatGPT / Codex / PWA
              │ HTTPS
              ▼
      reverse proxy ou tunnel
              │
       ┌──────┴─────────┐
       ▼                ▼
 API REST + MCP       web/PWA
       │
       ├────────► PostgreSQL
       ├────────► object storage FIT
       ├────────► Garmin Connect
       └────────► job table/outbox
                         ▲
                         │
                       worker
```

Componentes:

- `web`: build estático React/PWA;
- `api`: FastAPI com REST, OAuth resource metadata e MCP `/mcp`;
- `worker`: mesmo pacote de aplicação, processo separado;
- `postgres`: fonte de verdade e fila inicial;
- `object storage`: filesystem no início, S3 compatível quando necessário;
- `reverse proxy/tunnel`: TLS e exposição controlada;
- `backup`: rotina isolada de snapshot e verificação.

Não há RabbitMQ, Kubernetes nem microsserviços no MVP.

## 2. Endpoints operacionais

```text
https://swim.example.com/api/v1/...
https://swim.example.com/mcp
https://swim.example.com/.well-known/oauth-protected-resource
https://swim.example.com/health/live
https://swim.example.com/health/ready
```

O endpoint MCP de produção usa HTTPS estável e transporte streamable HTTP. Desenvolvimento pode usar tunnel seguro conforme validado no P00.

## 3. Ambientes

### 3.1 Local

- Docker Compose;
- PostgreSQL e storage locais;
- Garmin fake por padrão;
- fixtures FIT sanitizadas;
- OAuth/JWKS fixture para testes;
- MCP Inspector;
- bootstrap Garmin real somente opt-in;
- nenhum efeito Garmin real em CI.

### 3.2 Homologação pessoal

- domínio separado;
- conta/dados sanitizados ou ambiente real controlado;
- writes Garmin desabilitados por feature flag por padrão;
- workout canário identificável;
- plugin prerelease separado;
- métricas e logs ativos.

### 3.3 Produção pessoal

- VM Linux ou serviço equivalente;
- containers versionados;
- PostgreSQL persistente;
- TLS/tunnel;
- backup fora do host;
- allowlist de usuário;
- feature flags para writes e automações;
- acesso administrativo por chave/MFA.

## 4. Docker Compose alvo

```yaml
services:
  web:
    # build React/PWA e arquivos estáticos

  api:
    # FastAPI: REST + MCP + resource metadata

  worker:
    # job runner com heartbeat e leases

  postgres:
    # PostgreSQL, sem porta pública em produção

  proxy:
    # Nginx/Caddy ou origem para tunnel

  tunnel:
    # opcional; exposição HTTPS controlada

  backup:
    # pg_dump + object storage manifest + verificação
```

Regras:

- healthchecks reais;
- usuário não root;
- secrets por mecanismo do ambiente, não em imagem;
- limites de CPU/memória;
- volumes nomeados;
- rede interna para banco;
- imagem imutável por commit/release.

## 5. Modelo de jobs

A fila inicial usa PostgreSQL com `FOR UPDATE SKIP LOCKED`, lease, heartbeat e retry explícito. O job nunca mantém transação aberta durante chamada externa.

| Job | Trigger | Dedupe | Política |
|---|---|---|---|
| `garmin.sync_activities` | cron, PWA ou MCP | usuário + janela | backoff |
| `activity.fetch_file` | nova atividade | external id + tipo | backoff |
| `activity.normalize` | novo checksum | activity + parser version | determinístico |
| `activity.analyze` | normalização | activity + analysis version | determinístico |
| `metrics.aggregate_daily` | análise | usuário + data + versão | determinístico |
| `metrics.aggregate_weekly` | análise/fechamento | usuário + semana + versão | determinístico |
| `workout.publish_garmin` | ação aprovada | proposal + idempotency | reconcile first |
| `workout.schedule_garmin` | publish validado | binding + data | reconcile first |
| `garmin.reconcile_workouts` | cron/falha ambígua | usuário + janela | leitura antes de retry |
| `planning.generate_week` | manual/semanal | usuário + semana + input hash | rascunho apenas |
| `feedback.remind` | atividade sem feedback | activity + policy version | dedupe |
| `proposal.expire` | cron | proposal id | sem retry externo |
| `data.export` | usuário | request id | bounded |
| `data.delete` | confirmação | request id | staged/auditado |
| `backup.verify` | cron/manual | snapshot id | alerta em falha |

## 6. Automações permitidas

Podem ocorrer sem nova aprovação:

- importar e reconciliar dados;
- baixar/normalizar/analisar arquivos;
- recalcular métricas;
- expirar proposal;
- preparar rascunho de semana;
- emitir lembrete configurado;
- verificar token e backup.

Não podem ocorrer silenciosamente:

- publicar ou reagendar no Garmin;
- ativar plano novo;
- aumentar intensidade/carga;
- excluir treino/dado;
- ignorar feedback de dor;
- aprovar proposal.

## 7. Canais e notificações

Ordem inicial:

1. inbox dentro da PWA;
2. Web Push;
3. e-mail opcional;
4. canais externos apenas após necessidade real.

Toda notificação tem template versionado, dedupe key, preferências, horário silencioso e link para tela segura. Não incluir dado sensível no texto da notificação.

## 8. Logs

Formato JSON estruturado. Campos mínimos:

```text
timestamp level service environment correlation_id request_id user_id_hash
interface(rest|mcp|worker) tool_name use_case job_id proposal_id sync_run_id
provider outcome error_code duration_ms release_version
```

Nunca registrar:

- senha, token, cookie ou header de autorização;
- FIT/payload externo integral;
- nota livre integral;
- e-mail/serial sem necessidade;
- stack trace enviado ao cliente.

Logs de erro mantêm causa técnica internamente redigida e retornam código estável ao usuário/modelo.

## 9. Métricas

### 9.1 HTTP/MCP

- requests/calls por endpoint ou tool;
- latência p50/p95/p99;
- status/erro por código;
- autenticação negada e scope insuficiente;
- tool selection/eval regressions no pipeline de release;
- payload/result size;
- proposal criada, aprovada, expirada e executada.

### 9.2 Jobs e integrações

- jobs por status, idade e tentativas;
- duração da sincronização;
- cursor/staleness por usuário;
- atividades criadas/atualizadas/ignoradas;
- erros Garmin por categoria;
- reauth requerida;
- downloads e parse FIT com warning;
- reconciliações pendentes;
- publicação/agendamento por outcome.

### 9.3 Produto/treino

- sessões planejadas/concluídas;
- feedback pendente;
- volume semanal processado;
- dados incompletos;
- plano proposto/aceito;
- nenhuma métrica de produto deve expor PII em label.

## 10. Tracing

OpenTelemetry é opcional inicialmente, mas o código propaga correlation ID em:

```text
REST/MCP request
→ application use case
→ DB transaction
→ outbox/job
→ worker execution
→ Garmin/storage
→ reconciliation
```

Não colocar conteúdo sensível em span attributes.

## 11. Health e readiness

- `/health/live`: processo e event loop vivos;
- `/health/ready`: banco acessível, migrations compatíveis e storage essencial disponível;
- worker heartbeat com idade máxima;
- status detalhado apenas para usuário/admin autorizado;
- disponibilidade Garmin não derruba readiness da API;
- falha do IdP pode degradar novas autenticações sem apagar sessões válidas de forma insegura.

## 12. Painel operacional

Tela protegida com:

- versão da aplicação, schema, plugin, Skills e parser FIT;
- último sync e data staleness;
- conexão/reauth Garmin;
- jobs pendentes, falhos e em reconciliação;
- proposals pendentes/expiradas;
- tool errors recentes sanitizados;
- status de backups e último restore drill;
- uso de disco/storage;
- feature flags de escrita.

## 13. SLOs pessoais iniciais

Não são contrato comercial, mas orientam alertas:

- nenhum efeito externo duplicado por retry;
- nenhuma perda silenciosa de atividade importada;
- sync automática diária e manual disponível;
- tool de leitura p95 abaixo de 2 s quando atendida pelo banco/cache;
- ações externas assíncronas retornam job rapidamente;
- RPO inicial de 24 h;
- RTO documentado de poucas horas;
- alerta para backup falho, disco alto, worker parado, reauth e falhas repetidas.

## 14. Backups

Conteúdo:

- PostgreSQL;
- objetos FIT e manifests;
- configuração não secreta;
- versão das migrations e imagens;
- hashes de plugin/Skills necessários para auditoria.

Política inicial sugerida:

- snapshot diário, retenção 7 dias;
- semanal, retenção 4 semanas;
- mensal, retenção 6 meses;
- criptografia em trânsito e repouso;
- cópia fora do host;
- checksum e manifest;
- restore drill periódico em ambiente isolado.

Tokens só entram no backup quando houver desenho criptográfico e necessidade explícita. Caso contrário, reautenticar é preferível.

## 15. Restore

Procedimento:

1. provisionar host limpo;
2. restaurar versão compatível do banco;
3. restaurar objetos e verificar checksums;
4. executar migrations permitidas;
5. validar ownership e contagens;
6. iniciar API/worker com writes externos desabilitados;
7. rodar smoke read-only;
8. reconciliar Garmin;
9. reabilitar writes manualmente;
10. registrar `RestoreRun` e evidências.

## 16. Migrações e deploy

Deploy padrão:

1. CI e artefatos imutáveis;
2. backup/checkpoint;
3. migration expand compatível;
4. API/worker novos;
5. health/smoke tests;
6. release do plugin/Skills compatível;
7. observação;
8. cleanup posterior.

Mudanças destrutivas usam expand/contract. Não publicar Skill que dependa de tool ainda ausente. Não remover tool/schema enquanto algum plugin instalado depender da versão.

## 17. Storage FIT

Evolução:

```text
filesystem protegido
→ storage S3 compatível com versionamento/lifecycle
```

O banco guarda `StorageKey`, checksum, tamanho, MIME, parser version e ownership. Downloads são autenticados ou usam URL assinada curta. O MCP nunca retorna o binário bruto.

## 18. Runbooks mínimos

- Garmin reauth;
- sync atrasada;
- job stuck;
- rate limit/timeout Garmin;
- publicação com resultado ambíguo;
- parser FIT quebrado após mudança;
- banco sem espaço;
- object storage indisponível;
- OAuth/JWKS indisponível;
- rollback de app/plugin;
- restore completo;
- revogação e exclusão do usuário.
