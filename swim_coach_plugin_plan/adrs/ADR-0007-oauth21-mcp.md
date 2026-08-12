# ADR-0007 — OAuth 2.1 para MCP remoto

- **Status:** Accepted
- **Data:** 2026-08-05

## Contexto

Ferramentas acessam dados pessoais e ações. Endpoint público sem auth ou API key manual não atende o modelo de autorização esperado.

## Decisão

Implementar OAuth 2.1 compatível com autorização MCP: protected resource metadata, discovery, PKCE, resource/audience e scopes. Usar IdP estabelecido, Auth0 como default substituível, após spike de compatibilidade.

## Consequências

- integração segura e user-scoped;
- setup mais complexo;
- dependência de capabilities do IdP/host;
- testes negativos e metadata tornam-se gate;
- ambiente dev pode usar tunnel, mas dados privados não ficam anônimos em produção.
