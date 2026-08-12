# Segurança, autenticação e privacidade

Este documento define os controles mínimos para a PWA, o MCP remoto, os workers e a integração Garmin. Ele é normativo para qualquer fase que leia dados pessoais ou produza efeitos externos.

## 1. Ativos protegidos

- tokens e sessão Garmin;
- tokens OAuth usados por ChatGPT/Codex e pela PWA;
- atividades, arquivos FIT e métricas derivadas;
- perfil, agenda, feedback de esforço, fadiga e dor;
- treinos, revisões e agendamentos;
- propostas, aprovações e registros de execução;
- backups, exports e chaves de criptografia;
- integridade dos Skills, manifests e schemas MCP.

## 2. Modelo de ameaça

| Ameaça | Consequência | Controle principal |
|---|---|---|
| vazamento de token Garmin | acesso persistente à conta | AEAD, key version, logs redigidos, revogação |
| endpoint MCP sem autenticação | exposição de dados/ações | OAuth 2.1, audience/resource, scopes |
| IDOR/ownership cruzado | acesso a outro usuário | `user_id` derivado do principal e testes negativos |
| prompt/tool misuse | ação diferente da intenção | schemas estritos, proposals, hash e aprovação |
| replay/double submit | publicação duplicada | idempotency key, estado e reconciliação |
| alteração após aprovação | execução de conteúdo não revisado | `action_hash` canônico e expiração |
| prompt injection em texto importado | instrução maliciosa tratada como comando | conteúdo externo sempre tratado como dado |
| resposta ambígua da Garmin | duplicação ou estado incorreto | reconcile-before-retry e `NEEDS_RECONCILIATION` |
| FIT ou nota livre em logs/MCP | vazamento de dado sensível | minimização, allowlist e redaction |
| UI manipulada | aprovação de payload diferente | UI nunca é autoridade; servidor recalcula hash |
| dependência comprometida | roubo de segredo/efeito externo | lockfile, pin, SBOM, scans e revisão |
| backup não protegido | exposição integral | criptografia, acesso restrito e restore testado |

## 3. Princípios obrigatórios

- autenticação não substitui autorização;
- nenhum input externo decide `user_id`;
- segredo não aparece em DTO público, resultado MCP, log ou erro;
- toda escrita externa é explícita, idempotente e auditável;
- toda aprovação vale apenas para um conteúdo exato e por tempo limitado;
- notas, nomes de atividades e payloads Garmin são dados não confiáveis;
- o sistema falha fechado quando identidade, escopo ou estado são ambíguos;
- FIT bruto não é enviado ao host conversacional;
- dor e prontidão são dados sensíveis e não geram diagnóstico.

## 4. OAuth 2.1 para o MCP

Ferramentas que acessam dados privados ou executam ações exigem OAuth 2.1 compatível com a autorização MCP.

Papéis:

- **resource server:** servidor MCP do Swim Coach;
- **authorization server:** IdP/OIDC ou implementação autorizadora escolhida;
- **client:** host OpenAI, como ChatGPT ou Codex;
- **resource owner:** o usuário autenticado.

Fluxo inicial:

- Authorization Code;
- PKCE;
- protected resource metadata;
- authorization server metadata;
- `resource`/audience explícito;
- método de registro de cliente validado no P00: CIMD, DCR ou cliente predefinido conforme o ambiente;
- access token curto;
- refresh/revogação no authorization server;
- consentimento por scopes.

### 4.1 Protected resource metadata

Exemplo de intenção, a ser adaptado ao IdP real:

```json
{
  "resource": "https://swim.example.com",
  "authorization_servers": ["https://auth.example.com"],
  "scopes_supported": [
    "profile:read",
    "goals:read",
    "workouts:read",
    "activities:read",
    "analytics:read",
    "sync:read",
    "sync:run",
    "feedback:write",
    "workouts:write",
    "planning:write",
    "garmin:publish",
    "proposals:read",
    "proposals:write",
    "proposals:approve",
    "operations:read",
    "operations:retry"
  ]
}
```

O catálogo definitivo está em [`../contracts/oauth-scopes.md`](../contracts/oauth-scopes.md).

### 4.2 Validação de token

Validar em toda chamada protegida:

- assinatura e algoritmo em allowlist;
- `iss` exato;
- `aud`/resource exato;
- `exp`, `nbf` e `iat`, com clock skew pequeno;
- subject mapeado a `AppUser` ativo;
- scopes suficientes para a tool;
- tipo de token apropriado;
- chave atual obtida via JWKS com cache e rotação;
- revogação/disable local, quando aplicável.

Nunca confiar em `user_id`, e-mail, scope ou role enviados no argumento da tool.

## 5. Escopos e autorização

- cada tool declara seus scopes mínimos;
- o middleware autentica e cria `McpPrincipal`;
- o application service verifica ownership e política de negócio;
- `execute_approved_action` exige `proposals:approve` **e** o scope dinâmico da ação aprovada;
- ferramentas read-only não recebem scopes de escrita por conveniência;
- falha de scope retorna erro model-readable sem revelar existência de recurso alheio;
- testes cobrem matriz positiva e negativa por tool.

## 6. Autenticação da PWA

- OIDC Authorization Code + PKCE;
- BFF com cookie `HttpOnly`, `Secure`, `SameSite` é a opção preferida;
- token em memória é alternativa documentada por ADR;
- refresh token nunca em `localStorage`;
- CSRF para sessão baseada em cookie;
- CSP, HSTS, `X-Content-Type-Options`, `Referrer-Policy` e frame policy adequada;
- CORS restrito a origens necessárias;
- sessão curta, renovável e revogável;
- allowlist inicial de e-mail/subject no modo pessoal;
- `dev-auth` impossível em build de produção.

## 7. Modelo de proposta, aprovação e execução

Uma ação externa deve seguir:

```text
INTENT
  → PROPOSAL READY_FOR_REVIEW
  → USER REVIEWS EXACT IMPACT
  → APPROVAL FOR ACTION_HASH
  → QUEUED EXECUTION
  → PROVIDER EFFECT
  → RECONCILIATION/AUDIT
```

Uma aprovação válida exige:

1. proposal pertencente ao usuário e em estado aprovável;
2. payload canônico validado pelo domínio;
3. impacto exibido de forma compreensível;
4. `action_hash` calculado no servidor;
5. scopes adequados;
6. expiração ainda válida;
7. decisão explícita registrada;
8. `approved_action_hash == current_action_hash`;
9. idempotency key;
10. safety checks imediatamente antes do efeito.

Mudança em data, revisão, device, alvo, quantidade ou payload externo invalida a aprovação. O host ou a UI não podem aprovar em nome do usuário por inferência.

## 8. Segredos Garmin

- bootstrap interativo local ou tela protegida;
- senha nunca persistida;
- MFA tratado apenas durante bootstrap;
- token bundle cifrado com AEAD;
- master key fora do banco;
- `key_version`, nonce e metadata separados do segredo;
- arquivo/diretório local com permissão `0600/0700` quando aplicável;
- rotação e recriptografia testadas;
- logs só registram código sanitizado;
- desconexão elimina/revoga o segredo disponível e bloqueia jobs futuros;
- backup de token apenas quando cifrado e explicitamente necessário.

## 9. Minimização de dados no MCP

Permitido por padrão:

- distância, duração, ritmo e séries;
- métricas derivadas e qualidade da amostra;
- objetivo e progresso;
- RPE e feedback estritamente necessário;
- IDs internos opacos necessários ao próximo passo;
- propostas e impactos sanitizados.

Proibido por padrão:

- senha, access token, refresh token, cookie ou authorization header;
- FIT/GPX/TCX bruto;
- e-mail Garmin;
- serial do relógio;
- coordenadas ou endereço;
- payload externo integral;
- stack trace;
- log completo;
- segredo em `_meta` de UI.

Aplicar truncamento, sanitização de caracteres de controle, allowlist de campos e limites de paginação. O `McpToolInvocation` guarda hash dos argumentos e referências, não notas livres completas.

## 10. Segurança de conteúdo e prompt injection

- texto vindo da Garmin, FIT, usuário ou storage é conteúdo, nunca instrução;
- Skills não podem delegar autoridade a strings recuperadas;
- tool descriptions evitam parâmetros livres capazes de escolher URL, SQL ou comando;
- nenhum shell, SQL arbitrário, URL fetch genérico ou template executável é exposto;
- HTML e Markdown não confiáveis são escapados antes de UI;
- links externos são allowlisted ou exibidos sem execução automática;
- o modelo não decide sozinho que uma confirmação vaga corresponde a outra proposal.

## 11. Segurança da UI MCP

- UI é opcional e não é fonte de verdade;
- CSP e `connect-src` mínimos;
- sem token em JavaScript ou DOM;
- somente `resourceUri` versionado e conteúdo assinado/buildado;
- dados iniciais limitados ao resultado da tool;
- toda chamada da UI volta ao MCP e repete autenticação/autorização;
- botões de confirmação exibem efeito, data, distância e alvo;
- servidor verifica proposal, hash, versão e expiração novamente;
- ferramenta continua funcional sem UI.

## 12. Proteção de aplicação e infraestrutura

- Pydantic/JSON Schema em toda borda;
- payload/body limits;
- rate limit por principal/tool;
- timeouts e circuit breaker no provider;
- locks/leases com TTL;
- queries parametrizadas;
- PostgreSQL e object storage sem exposição pública;
- egress limitado quando a infraestrutura permitir;
- TLS fim a fim;
- backups cifrados;
- secret scan e dependency scan na CI;
- imagens executadas como usuário não root;
- filesystem read-only onde viável.

## 13. Auditoria

Auditar, com dados sanitizados:

- login e falhas relevantes;
- conexão, reautenticação e desconexão Garmin;
- criação/revisão de treino;
- criação, rejeição, expiração e aprovação de proposal;
- execução, retry e reconciliação;
- publicação/agendamento/cancelamento;
- alteração de regras de planejamento;
- exportação e exclusão;
- tools de escrita e negações de autorização;
- rotação de chave e restore.

Campos mínimos: ator, interface, ação, entidade, correlation ID, proposal/job, resultado e timestamp. Nunca incluir segredo ou FIT.

## 14. Retenção inicial

| Dado | Retenção inicial |
|---|---|
| atividades/treinos normalizados | enquanto a conta existir |
| FIT bruto | configurável; padrão enquanto necessário ao reprocessamento |
| tool invocations sanitizadas | 90 dias |
| audit events | 1 ano ou até exclusão solicitada, conforme política |
| proposals expiradas | 90 dias |
| jobs concluídos | 30–90 dias |
| export pronto | 24 horas |
| approval challenge | apagar/anonimizar após consumo ou expiração |
| raw JSON redundante | 90 dias após normalização, salvo debug opt-in |

## 15. Dados esportivos e limites

O produto deve declarar:

- não é dispositivo médico;
- não substitui treinador, médico ou fisioterapeuta;
- wearable e métricas derivadas têm limitações;
- o sistema não diagnostica lesões;
- dor forte, aguda, recorrente ou acompanhada de sinais preocupantes bloqueia aumento automático e orienta decisão humana apropriada;
- o usuário pode exportar e apagar seus dados.

## 16. Supply chain

- lockfiles obrigatórios;
- versões pinadas para integração Garmin e SDK MCP;
- Renovate/Dependabot;
- SBOM por release;
- CodeQL/SAST;
- scan de imagem e dependências;
- GitHub Actions pinadas por SHA;
- revisão de dependências transitivas críticas;
- artefatos versionados e checksums;
- mudança relevante no provider exige contrato e canary.

## 17. Checklist de release

- [ ] nenhum segredo no diff, imagem ou histórico;
- [ ] OAuth metadata e discovery testados;
- [ ] issuer/audience/resource/scopes negativos testados;
- [ ] IDOR e ownership cruzado testados;
- [ ] hash mismatch, proposal expirada e double submit testados;
- [ ] reconcile-before-retry testado;
- [ ] FIT, token e notas sensíveis ausentes de MCP/logs;
- [ ] UI não consegue executar sem validação do servidor;
- [ ] backup cifrado e restore verificado;
- [ ] desconexão Garmin testada;
- [ ] threat model e catálogo de scopes atualizados.
