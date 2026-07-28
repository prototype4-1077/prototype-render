# Prototype Render (public runner)

Public execution environment for the Prototype video pipeline.

**This repository contains code only.** Scripts, narration, learning memory,
telemetry, and finished videos live in a separate **private** content
repository and are pulled in at render time with a scoped token.

Renders can only be started by accounts with write access — `workflow_dispatch`,
`push`, and `repository_dispatch` all require it. Fork pull requests never
receive secrets.
