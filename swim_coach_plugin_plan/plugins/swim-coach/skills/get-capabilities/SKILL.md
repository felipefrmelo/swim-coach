---
name: swim-coach-capabilities
description: Verify that the Swim Coach plugin and its harmless capability endpoint are available without reading private training data or performing writes.
---

# Verify Swim Coach capabilities

Use this workflow only for the P00 platform spike.

1. Call `get_capabilities` when the MCP test connection is available.
2. Report the server version, release mode, harmless tools, and missing prerequisites.
3. Never request athlete data, Garmin credentials, tokens, activity IDs, or health information.
4. Never call another Swim Coach tool.
5. Do not claim Garmin, OAuth, writes, or production deployment are complete unless the tool result proves it.
6. If the MCP connection is absent, say the Skill loaded and the test connection still needs registration.
