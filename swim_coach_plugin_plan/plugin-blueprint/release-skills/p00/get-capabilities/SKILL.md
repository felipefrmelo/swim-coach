---
name: swim-coach-capabilities
description: Verify that the Swim Coach plugin and its harmless capability endpoint are available without reading private training data or performing writes.
---

# Verify Swim Coach capabilities

Use this workflow only for the P00 platform spike.

1. Call `get_capabilities` when the MCP test connection is available.
2. Report the server version, enabled release mode, available harmless tools, and any missing platform prerequisite.
3. Do not request athlete data, Garmin credentials, tokens, activity IDs, or health information.
4. Do not call any other Swim Coach tool.
5. Do not claim that Garmin, OAuth, writes, or production deployment are complete unless the tool result explicitly proves them.
6. When the MCP connection is absent, state that the Skill loaded but the test connection still needs to be registered.
