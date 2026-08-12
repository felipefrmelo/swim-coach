# Public readiness assessment — separado do release pessoal

Estado: **NOT READY FOR PUBLIC SUBMISSION**.

O release 1.0 é pessoal e single-tenant por política/allowlist. Não publicar nem
submeter a marketplace público até todos os itens abaixo terem dono e evidência:

- autorização formal e termos aplicáveis para integração Garmin;
- DPA, política de privacidade pública, base legal, prazos e canal de suporte;
- isolamento multiusuário sob load/abuse, rate limit distribuído e quotas;
- gestão de chaves/secrets e backups fora do host único;
- monitoramento 24×7, SLO, resposta a incidentes e comunicação de violação;
- revisão humana de conteúdo de saúde, claims e limites do treinador;
- accessibility/browser/device matrix pública;
- pentest independente de OAuth, MCP, IDOR, CSRF, export e deletion;
- processo de release/rollback com imagens assinadas e provenance verificável.

Nenhuma automação deste repositório realiza submissão pública.
