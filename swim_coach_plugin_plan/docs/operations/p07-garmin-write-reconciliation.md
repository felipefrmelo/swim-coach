# P07 — Publicação Garmin e reconciliação

## Controles

- leitura: `SWIM_COACH_GARMIN_READ_ENABLED`;
- kill switch de escrita: `SWIM_COACH_GARMIN_WRITE_ENABLED` (padrão `false`);
- modo: `disabled`, `fake` ou `live`;
- produção rejeita `fake`;
- `live` exige credencial Garmin cifrada e, por padrão, título iniciado por `[CANARY]`;
- preview nunca chama a Garmin; somente a aprovação do hash exato enfileira trabalho.

## Canário descartável real

1. Confirme que a conexão/sincronização P02 está saudável.
2. Configure `WRITE_MODE=live`, `WRITE_ENABLED=true` e mantenha `WRITE_CANARY_ONLY=true`.
3. Rode:

   ```bash
   uv run python backend/scripts/probe_garmin_write_canary.py --acknowledge-external-write
   ```

4. Na PWA, crie um treino pequeno e descartável com título iniciado por `[CANARY]`.
5. Aprove localmente, agende, abra a proposta e confira distância, data, dispositivo e hashes.
6. Clique uma vez no verbo explícito. Aguarde `Publicado e agendado`.
7. Recarregue a ação: ela deve continuar `SUCCEEDED`; não clique/crie nova proposta.
8. Confirme na Garmin uma única entrada na biblioteca e no calendário.
9. Desligue imediatamente `SWIM_COACH_GARMIN_WRITE_ENABLED` após a prova.

O script não publica nada nem recebe senha. Credenciais continuam no terminal seguro do fluxo P02.

## Resultado ambíguo

Não faça retry manual cego. O worker consulta primeiro:

- biblioteca pelo marcador `[swim-coach:<revision_hash>]` após create ambíguo;
- calendário do mês por workout/date após schedule ambíguo.

Se a leitura não confirma o efeito, proposal, execution, binding e job ficam
`NEEDS_RECONCILIATION`. Procedimento:

1. mantenha o kill switch desligado;
2. pesquise biblioteca e calendário pelo título/data/hash, sem criar ou excluir;
3. compare com `external_workout_binding` e audit trail;
4. se o efeito existir, confirme o binding por uma correção operacional auditada;
5. se não existir, cancele a ação antiga e gere nova proposta; não reanime o job antigo;
6. nunca apague remotamente de forma automática. Remoção exige proposta separada futura.

## Rollback

Desligar o kill switch impede novas aprovações e o worker recusa jobs de escrita. Jobs já
ambíguos permanecem preservados para investigação. O MVP não executa delete/unschedule remoto.
