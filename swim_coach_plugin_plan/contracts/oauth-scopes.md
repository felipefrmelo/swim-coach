# OAuth scopes — MCP v2 pessoal

| Scope | Uso | Risco |
|---|---|---|
| `coach` | ler e operar todo o ciclo pessoal de treino, inclusive sincronizar e publicar no Garmin | dados privados + open-world |

O conector solicita os scopes padrão `openid email profile offline_access` e o
único scope customizado `coach`. O backend continua aplicando ownership em todas
as entidades e não usa o scope amplo para autorizar exportação ou exclusão de
conta. Esses fluxos administrativos permanecem exclusivos do site autenticado
para oferecer revisão visual e reduzir risco. Isso não muda a hierarquia do
produto: o ChatGPT é a interface principal para o uso cotidiano, enquanto o
site é auxiliar para administração, configuração, diagnóstico e contingência.

Os scopes granulares da versão 1 são legados e não são anunciados pelo MCP v2.
Uma reconexão do conector é necessária na migração para `coach`.
