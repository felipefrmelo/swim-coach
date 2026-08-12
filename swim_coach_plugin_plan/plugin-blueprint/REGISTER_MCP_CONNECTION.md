# Registrar a conexão MCP

1. Conclua P05 e exponha `/mcp` via HTTPS/tunnel.
2. Teste com MCP Inspector.
3. Habilite developer mode em uma superfície suportada.
4. Adicione o servidor MCP e conclua OAuth.
5. Copie o ID técnico de conexão.
6. Execute `@plugin-creator`/`$plugin-creator` para conectar este plugin ao ID.
7. Revise o `.app.json` gerado.
8. Adicione `"apps": "./.app.json"` ao manifesto.
9. Não commite dados que a superfície classificar como secretos ou específicos de conta sem revisão.
10. Instale via marketplace pessoal e registre evidência.
