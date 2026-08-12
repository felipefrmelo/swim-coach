# P12 security review e threat-model delta

## Novas superfícies

| Superfície | Ameaça principal | Controle implementado |
|---|---|---|
| backup | leitura/tamper/path traversal | AES-256-GCM, chave privada, checksum, archive allowlist, restore vazio |
| export | IDOR, vazamento de token/FIT adulterado | ownership, sessão, CSRF na criação, exclusões explícitas, checksum, expiração/no-store |
| delete | CSRF/acidente/replay/órfão externo | request idempotente, frase UUID exata, cooling-off, revogação/cancelamento antes do cascade |
| API pública | flood/body excessivo/clickjacking | limites read/write, 1 MiB, CSP, frame deny, HSTS em produção |
| containers | root/escape/escrita indevida | UID non-root, cap-drop, no-new-privileges, rootfs read-only e tmpfs no overlay |

## Revisão de autorização e dados

Toda consulta de export/delete recebe `user_id` da sessão, nunca do body. Um ID
pertencente a outra conta vira not-found. A exportação omite hashes de sessão,
tokens OAuth, credencial Garmin criptografada e raw payload livre; FIT só entra
após checksum. A confirmação desabilita a conta, revoga sessões e token Garmin,
cancela jobs/proposals e só depois agenda o cascade. O tombstone perde `user_id`
por `SET NULL`, preservando apenas estado e timestamps operacionais.

## Scans e revisão

O gate executa Ruff/ESLint/mypy/TypeScript, testes de auth/ownership/IDOR,
`pip-audit`, `pnpm audit`, Gitleaks em histórico e árvore, SBOM CycloneDX/SPDX e
Trivy nas quatro imagens. Achado alto/crítico bloqueia release; falso positivo
precisa de justificativa com pacote, versão, alcance e expiração.

## Riscos residuais aceitos no release pessoal

- rate limit é por processo/IP; uma publicação multi-instância requer store
  distribuído e proteção no ingress;
- remoção de artefato ocorre após commit do cascade. Falha de filesystem pode
  deixar arquivo órfão sem referência, tratado por reconciliação/runbook;
- Garmin é integração não oficial e `429` deve ser tratado com backoff, nunca
  como falha de autenticação;
- a prontidão pública não está concedida: suporte, multiusuário e revisão dos
  termos Garmin continuam gates separados.
