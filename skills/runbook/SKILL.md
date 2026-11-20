---
name: runbook
description: Builds the data migration runbook from the template library, with AI only choosing and ordering allowed steps, never writing commands. Use it when adding templates or changing how runbook steps are chosen.
---

# Runbook

Part of: sovereign-shift. Code: `sovereign_shift/runbook/build.py`. Templates: `runbook/templates/*.yaml`. Design: `PLAN.md` (Data migration runbook).

## Rules
- Commands come only from templates. The AI returns step ids, order, inputs and notes, and the validator drops anything not in the library.
- Customer inputs always render as `<CUSTOMER: ...>`. Never put a real secret in a runbook.
- A resource without a template goes to the report as manual work, in prose.
- Root disks move with their instance, so they get no runbook of their own.
