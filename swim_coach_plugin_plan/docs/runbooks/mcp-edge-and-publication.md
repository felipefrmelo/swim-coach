# MCP, borda e publicação Garmin

| Evidência observada | Categoria | Ação |
|---|---|---|
| 403, securitySource=firewallCustom, originResponseStatus=0 | EDGE_FIREWALL_BLOCKED | Localizar evento pelo ray ID no Cloudflare; origin não foi atingida |
| OAuth 401/403, challenge/token/scopes | OAUTH_AUTHORIZATION_REQUIRED | Reautorizar a conexão correta; não pedir tokens pelo chat |
| MCP 403 com origin atingida | MCP_PERMISSION_DENIED | Verificar scope coach e ownership |
| Backend 5xx | BACKEND_UNAVAILABLE | Verificar health, versão/schema, logs pelo correlation ID |
| Garmin 401/403 | GARMIN_AUTH_REQUIRED | Bootstrap seguro de sessão; manter kill switches |
| Garmin 5xx/network | GARMIN_UNAVAILABLE | Retry limitado/reconciliação, sem duplicar template |
| Payload 422 | SCHEMA_INVALID | Seguir paths e repair_hint; reler estado e tentar uma vez |

403 sozinho não prova bloqueio na borda, OAuth nem Garmin. Não registrar header
Authorization, cookies, credenciais Garmin, FIT ou corpos externos privados.
Guardar somente categoria, status HTTP e identificadores sanitizados de pedido.

## Cloudflare

1. Confirmar host exato `swim-coach.ozix.com.br`, POST e caminho `/mcp/`, ray ID,
   regra customizada responsável e originResponseStatus.
2. Inspecionar expressão/regra e sua finalidade antes de editar. Se aplicável,
   ajustar somente a condição que bloqueia esse endpoint autenticado. Não criar
   bypass global, permitir qualquer origem ou remover OAuth/scope/rate limits.
3. Reexecutar um MCP autenticado com identidade sintética de desenvolvimento:
   initialize, tools/list, get_coach_operations e preview_calendar. Esperar
   sucesso autenticado e 401 sem token. Não publicar Garmin real como teste.
4. Sem acesso ao painel/API Cloudflare, registrar dependência externa; o backend
   não consegue reparar tráfego barrado antes de atingir o servidor.

## Publicação parcial

Consultar `get_publication_status` com os IDs do lote. PUBLISHED exige binding
confirmado da revisão e data locais atuais; status de job sozinho não basta.
A resposta mostra local_date, remote_date, job_state, erro sanitizado e horário
da última confirmação persistida. Esse horário não é uma consulta Garmin nova.

O worker confirma a nova entrada antes de remover a antiga. Se houver falha após
criar/agendar, o retry procura o objeto por source hash e data antes de repetir.
Uma falha na retirada da data antiga deixa o job/binding fora de sincronia;
reexecutar a operação idempotente/reconciliação, sem apagar atividades realizadas.
Antes de confirmar sucesso, verificar que só há a data desejada no calendário.
Se o resultado for ambíguo, interromper retries automáticos e reconciliar.

## Pós-deploy

Exigir CI verde no SHA exato. O pipeline verifica main, backup, migração,
readiness, raiz pública, login 303 e MCP sem token 401. Fazer também leitura MCP
autenticada pela conexão existente: contexto, meta/ciclo, workouts e status,
sem criar prescrição ou publicar treinos reais. O smoke autenticado sintético é
coberto por testes de integração; conferir as evidências separadamente do smoke
público de produção. Não declarar um deploy só porque o job foi enfileirado.
