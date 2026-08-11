# Exemplos de contratos e objetos

Estes arquivos são fixtures explicativas, sem segredo ou identificador real:

- `athlete-profile-felipe.json`: perfil inicial e restrições de produto;
- `workout-technique-1600m-20m.json`: treino canônico válido, total de 1.600 m em piscina de 20 m;
- `weekly-plan-proposal.json`: proposta de semana, nunca ativação automática;
- `action-proposal-garmin-publish.json`: efeito externo revisável e vinculado por hash;
- `tool-result-latest-swim.json`: envelope MCP headless;
- `post-swim-feedback.json`: input de feedback pós-treino.

O validator confere os exemplos que possuem JSON Schema normativo. Fixtures de domínio sem schema dedicado devem ser convertidas em testes tipados na fase correspondente.
