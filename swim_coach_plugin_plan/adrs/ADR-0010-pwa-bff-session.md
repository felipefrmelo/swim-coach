# ADR-0010 — BFF OIDC e sessão opaca para a PWA

- **Status:** Accepted
- **Data:** 2026-08-11

## Contexto

A P01 precisa autenticar a PWA sem expor tokens OIDC ao JavaScript ou persistir
refresh tokens no navegador. A especificação de segurança prefere BFF/cookie,
mas exige uma decisão complementar para a estratégia concreta.

## Decisão

O backend executa Authorization Code + PKCE, valida `iss`, `aud`, assinatura,
expiração e nonce do ID token, aplica allowlist e cria uma sessão local opaca.
O navegador recebe apenas um cookie de sessão `HttpOnly`, `Secure` em produção e
`SameSite=Lax`; mutações exigem CSRF vinculado à sessão. O banco guarda hashes do
token de sessão e do CSRF. Access/refresh tokens do IdP não são persistidos.

`dev-auth` existe apenas quando explicitamente habilitado fora de produção e
continua sujeito à mesma allowlist e à mesma sessão. Configuração de produção
com `dev-auth` falha durante o bootstrap.

## Consequências

- tokens do IdP não ficam disponíveis ao bundle da PWA;
- logout e expiração são revogáveis no servidor;
- o backend assume o custo do callback OIDC, estado PKCE e armazenamento de
  sessões;
- uma sessão local não equivale a refresh silencioso do IdP; nova autenticação é
  exigida após expirar;
- testes E2E locais usam `dev-auth` explícito, enquanto testes de contrato cobrem
  discovery, PKCE e validação criptográfica OIDC.
