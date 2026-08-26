# OAuth scopes — MCP v2 pessoal

| Scope | Uso | Risco |
|---|---|---|
| `coach` | ler e operar todo o ciclo pessoal de treino, inclusive sincronizar e publicar no Garmin | dados privados + open-world |

O conector solicita os scopes padrão `openid email profile offline_access` e o
único scope customizado `coach`. O backend continua aplicando ownership em todas
as entidades e não usa o scope amplo para autorizar exportação ou exclusão de
conta. Esses fluxos permanecem exclusivos da PWA autenticada.

Os scopes granulares da versão 1 são legados e não são anunciados pelo MCP v2.
Uma reconexão do conector é necessária na migração para `coach`.
