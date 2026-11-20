# AI providers and agents

## Where AI is used
Four jobs. Everything else is deterministic.
1. Alternatives for resources with no Leaseweb equivalent (translator agent).
2. Personalised data migration runbook from the template library (runbook agent).
3. Review of generated firewall rules (reviewer agent). It flags problems and doesn't write rules.
4. Plain-language summary of the report (explainer agent).

`--no-ai` produces the full output with template defaults, and the report lists the gaps as manual work.

## Provider choice
The team picks the provider and key. Notes below are on the options we looked at.

## OpenRouter, with EU in-region routing
Sources: https://openrouter.ai/docs/guides/features/in-region-routing, https://openrouter.ai/docs/guides/features/sovereign-ai, https://openrouter.ai/blog/announcements/us-in-region-routing (checked 2026-11-20)
- Base URL `https://eu.openrouter.ai/api/v1`. Prompts and completions are decrypted in the EU and only sent to providers in the EU/EEA, UK or Switzerland. Same API key and model ids, smaller model list.
- Caveats: the docs list it for Business/Enterprise plans. **Verify our key works before the event.** Account and operational records and the Batch API stay in the US. One anecdotal report of a 522 error on the EU host.
- Workspace-level enforcement: set the workspace guardrail's allowed data regions to Europe.
- Fallback if the EU host isn't available: `openrouter.ai` with `provider: { only: [<EU providers>], data_collection: "deny" }`. Weaker guarantee. Say so in the pitch if we use it.
- Second fallback: Ollama locally. Slow without a GPU (10-30 s per call), so run the demo from the cache.

## Client design
- One client: the `openai` Python SDK with configurable `base_url` and `api_key`. Covers OpenRouter (EU or global), Ollama (`http://localhost:11434/v1`) and any OpenAI-compatible endpoint.
- Config: `SOVEREIGN_AI_BASE_URL`, `SOVEREIGN_AI_API_KEY`, `SOVEREIGN_AI_MODEL`, with optional per-agent overrides.
- Structured output with a JSON schema on every call. Validate with pydantic. On failure, retry once, then fall back (see each agent).
- **Cache** every response keyed by a hash of its input, in `out/.cache/`. The demo replays cached answers, so it doesn't depend on network or model speed.
- **Redaction** before every call: keys, passwords, tokens, `user_data` contents, account IDs, host IP addresses. Keep CIDRs in security group rules: the reviewer needs them. The model only sees resource metadata.

## Agents (plain Python, no framework)

### 1. Translator
- Input: one unmapped resource, its graph neighbours, the Leaseweb schema subset, and 2-3 few-shot examples from the provider's `examples/`.
- Output: `{alternative, justification, effort, manual_steps[], confidence}`.
- Fallback: `manual`, no suggestion.

### 2. Runbook
- Input: one mapped resource, the template steps for its type from `runbook/templates/`, and the target Leaseweb values.
- Output: step ids in order, input values, notes, `not_capable[]` (shape in `docs/contracts.md`). The agent never writes a command. Our code renders commands from the templates.
- Validator: step ids must exist in the template and inputs must be declared in it. Customer inputs always render as `<CUSTOMER: ...>`. Anything else is dropped.
- Fallback: template default steps, flagged `generated_by: template-default`.

### 3. Reviewer
- Input: the Leaseweb security group rules from `finalize.json`, and the source AWS SG rules.
- Output: `{ok, issues: [{rule, problem, suggested_change}]}`. Suggested changes are shown to the user. They are not applied automatically.
- Fallback: rules are applied as generated, marked "unreviewed".

### 4. Explainer
- Input: `report.json`. Cut first if time runs short.
- Output: a short summary, plus an optional architecture paragraph from the graph. English by default, Portuguese on request.
- Fallback: no summary section.

## Model choice
A cheap, fast model for the translator and explainer. A stronger model for the runbook agent and reviewer, since their output is checked and more consequential. Pick from what the EU endpoint lists (e.g. Mistral models) once the key is confirmed.
