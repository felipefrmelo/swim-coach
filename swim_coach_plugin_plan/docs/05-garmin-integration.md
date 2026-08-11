# Integração Garmin

## 1. Estratégia

A integração inicial usa `python-garminconnect`, mas nenhuma outra parte do sistema deve importar a biblioteca diretamente.

```python
class GarminProvider(Protocol):
    async def validate_connection(
        self, user_id: UserId
    ) -> ProviderConnectionStatus: ...

    async def list_devices(
        self, user_id: UserId
    ) -> list[GarminDeviceDTO]: ...

    async def list_activities(
        self,
        user_id: UserId,
        cursor: SyncCursor | None,
        filters: ActivityFilter,
    ) -> ProviderPage[GarminActivitySummaryDTO]: ...

    async def get_activity(
        self, user_id: UserId, external_id: ExternalId
    ) -> GarminActivityDetailDTO: ...

    async def download_activity_file(
        self,
        user_id: UserId,
        external_id: ExternalId,
        file_type: ActivityFileType,
    ) -> bytes: ...

    async def create_workout(
        self, user_id: UserId, payload: GarminWorkoutDTO
    ) -> ExternalWorkoutResult: ...

    async def update_workout(
        self,
        user_id: UserId,
        external_id: ExternalId,
        payload: GarminWorkoutDTO,
    ) -> ExternalWorkoutResult: ...

    async def get_workout(
        self, user_id: UserId, external_id: ExternalId
    ) -> GarminWorkoutDTO | None: ...

    async def schedule_workout(
        self,
        user_id: UserId,
        external_id: ExternalId,
        when: LocalDateTime,
    ) -> ExternalScheduleResult: ...

    async def unschedule_workout(
        self, user_id: UserId, external_schedule_id: ExternalId
    ) -> ExternalDeleteResult: ...

    async def delete_workout(
        self, user_id: UserId, external_id: ExternalId
    ) -> ExternalDeleteResult: ...
```


Implementações:

```text
GarminProvider
├── UnofficialGarminConnectProvider   ← inicial
└── OfficialGarminConnectProvider     ← futura
```

## 2. Bootstrap de autenticação

Fluxo recomendado:

1. Executar `scripts/garmin_bootstrap.py` de forma interativa.
2. Solicitar e-mail e senha sem eco.
3. Solicitar código MFA quando necessário.
4. Autenticar diretamente com a Garmin por HTTPS.
5. Receber o bundle de tokens.
6. Descartar senha e código MFA da memória o mais cedo possível.
7. Criptografar tokens com chave mestra externa.
8. Salvar `GarminConnection`.
9. Testar uma chamada somente leitura.
10. Registrar auditoria sem segredo.

A PWA não precisa receber a senha Garmin. Uma tela pode apenas mostrar instruções, estado e necessidade de reautenticação.

## 3. Armazenamento de token

Opção recomendada:

- bundle criptografado no PostgreSQL com AES-GCM;
- chave mestra em secret do ambiente;
- versão de chave registrada;
- decriptar apenas dentro do worker;
- materializar temporariamente em `tmpfs` caso a biblioteca exija arquivo;
- ler tokens atualizados após a chamada;
- recriptografar na mesma operação;
- apagar arquivo temporário.

Nunca registrar:

- access token;
- refresh token;
- senha;
- código MFA;
- corpo completo de erro de autenticação.

## 4. Concorrência

A sessão/tokens Garmin não devem ser usados simultaneamente por dois jobs do mesmo usuário.

Usar um dos mecanismos:

- PostgreSQL advisory lock por `user_id`; ou
- linha `garmin_connection` com `SELECT ... FOR UPDATE` durante atualização de token.

O lock deve ter timeout e liberar em erro.

## 5. Sincronização de atividades

### Sincronização incremental

1. Ler `SyncCursor`.
2. Consultar uma janela com sobreposição, por exemplo 48 horas antes do watermark.
3. Listar atividades.
4. Filtrar natação em piscina para processamento completo.
5. Fazer upsert do resumo por `external_activity_id`.
6. Buscar detalhes quando novo ou alterado.
7. Baixar FIT quando necessário.
8. Persistir payload bruto e checksum.
9. Normalizar.
10. Associar a treino planejado.
11. Calcular análise.
12. Atualizar agregados diários/semanais.
13. Avançar cursor somente após sucesso dos itens obrigatórios.

A sobreposição permite capturar atividades editadas ou sincronizadas com atraso.

### Backfill

- padrão inicial configurável: 90 dias;
- paginação e checkpoint;
- prioridade menor que sincronização recente;
- possibilidade de interromper e retomar;
- não baixar FIT repetido se checksum/versão não mudou.

## 6. Publicação de treino

1. Receber proposta aprovada.
2. Verificar que `action_hash` ainda corresponde à revisão.
3. Validar novamente o treino.
4. Compilar para Garmin.
5. Criar ou atualizar treino externo.
6. Agendar na data local.
7. Opcionalmente enviar ao dispositivo primário.
8. Persistir IDs externos, payload e hash.
9. Alterar estado local somente após resposta confirmada.
10. Notificar resultado.

## 7. Idempotência

Chave sugerida:

```text
garmin:publish:{user_id}:{workout_id}:{revision_id}:{scheduled_date}
```

Se o job for repetido:

- consultar binding existente;
- comparar payload hash;
- reutilizar ou atualizar;
- nunca criar cópias silenciosas.

## 8. Erros normalizados

| Código interno | Significado | Ação |
|---|---|---|
| `GARMIN_AUTH_REQUIRED` | refresh inválido/revogado | marcar `reauth_required` |
| `GARMIN_RATE_LIMITED` | limite externo | retry com backoff |
| `GARMIN_NETWORK_ERROR` | timeout/DNS/5xx | retry |
| `GARMIN_BAD_REQUEST` | payload incompatível | não repetir; revisar compilador |
| `GARMIN_NOT_FOUND` | entidade removida | reconciliar binding |
| `GARMIN_CONFLICT` | duplicidade/estado | buscar estado atual |
| `GARMIN_SCHEMA_CHANGED` | resposta inesperada | abrir alerta e preservar bruto |
| `GARMIN_UNKNOWN_ERROR` | erro não classificado | retry limitado + intervenção |

## 9. Política de retry

- 5xx e rede: backoff exponencial com jitter;
- 429: respeitar cabeçalho quando disponível;
- 401: uma tentativa de refresh, depois `reauth_required`;
- 4xx de payload: sem retry automático;
- máximo configurável;
- dead-letter lógico na tabela `job` após esgotar tentativas.

## 10. Migração para APIs oficiais

A interface permite substituir a implementação sem alterar planejamento, análise ou UI.

As APIs oficiais devem assumir:

- consentimento OAuth 2.0;
- Activity API para atividades e arquivos;
- Training API para treinos e planos;
- webhooks/push quando disponíveis;
- gestão de scopes;
- estado de consentimento por usuário.

A migração precisa de:

- um novo provider;
- migração de bindings externos;
- reconciliação de atividades por data/checksum;
- execução paralela em modo sombra antes do corte.

---

## 11. Fronteiras do provider

- o domínio produz `WorkoutRevision` canônica;
- `GarminWorkoutCompiler` transforma a revisão em `GarminWorkoutDTO` e aplica a capability matrix;
- `GarminProvider` apenas autentica e troca DTOs com o serviço externo;
- nenhum application service importa classes de `python-garminconnect`;
- o provider recebe `user_id` explicitamente e resolve o segredo na infraestrutura;
- respostas externas são mapeadas antes de cruzar a porta;
- erros são convertidos para `GarminProviderError`;
- leitura e escrita têm timeouts, rate limiting e telemetry próprios;
- mudanças incompatíveis na porta exigem nova versão e ADR.

## 12. Bootstrap seguro

1. executar CLI local interativa;
2. login e MFA acontecem no terminal do usuário;
3. biblioteca grava token bundle em diretório temporário protegido;
4. comando cifra o bundle com a chave do ambiente alvo;
5. importação autenticada associa o segredo ao `GarminConnection`;
6. arquivo temporário é destruído;
7. senha nunca chega ao banco, MCP, PWA, logs ou host.

## 13. Estratégia de escrita

- compilar localmente e calcular `compiled_hash`;
- procurar binding existente para revisão/hash;
- criar `ActionProposal`;
- após aprovação, enfileirar job;
- publicar;
- persistir IDs externos na mesma transação da conclusão;
- agendar como etapa separada idempotente;
- reconciliar antes de retry quando a resposta for ambígua.

## 14. Risco da integração não oficial

O provider pessoal pode quebrar quando a Garmin alterar endpoints. Mitigações:

- testes de contrato contra fixtures;
- smoke test real manual protegido;
- feature flag de escrita;
- circuit breaker e backoff;
- payload bruto/erro sanitizado para diagnóstico;
- interface compatível com futura API oficial;
- PWA permite exportar treino mesmo quando publicação estiver indisponível.
