<!-- love-render src=plan.json sha=6583ad64 do not hand-edit -->

# E3-S1 Prompt firewall

Epic E3: Prompt and context boundary (UserPromptSubmit plus JIT injection). Sprint 3. Gate code-review.

## Why
As an operator, I want prompts like 'just comment it out' or 'skip the tests' met with an injected discipline reminder before the agent complies, so violations stop at the source.

## Done when
- prompt_submit.py matches a small reviewed rule list against the prompt field, injects additionalContext by default (D9), and offers block-mode as a config opt-in
- the at-mention rule (config-gated, default off) blocks literal @filename tokens forcing an explicit Read, for data-boundary mode
- the keyword-to-context map (config-gated, default off) injects mapped guidance deterministically
- no prompt text is persisted anywhere

## Execution
- [x] E3-S1-T1: prompt_submit.py firewall (inject-first)
- [x] E3-S1-T2: At-mention bypass rule (config-gated)
- [ ] E3-S1-T3: Keyword-to-context injection map (config-gated)

