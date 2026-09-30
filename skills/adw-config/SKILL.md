---
name: adw-config
description: Show the ADW project policy for the current directory.
disable-model-invocation: true
argument-hint: <status>
---

Run the installed `adw-config` executable exactly once with the `status` argument:

```sh
adw-config status
```

Relay the printed lines unchanged. They name the policy file, the tests policy, each family as on or off, and every rule gate that differs from its default.

Never run `adw-config tests` or `adw-config family` yourself. ADW blocks every agent call that changes the policy, because only the user sets it. If the user asks for a change, give them the exact command to run in their own terminal:

```sh
adw-config tests allow|deny
adw-config family NAME on|off
```
