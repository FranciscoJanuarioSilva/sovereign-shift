# Assessment sections

`sovereign-shift assess` adds four sections to the report, all computed by rules from the inventory, graph, findings and mapping. The exact rubrics are the `skills/assess-*/SKILL.md` files (the code implements them, `tests/test_skills.py` keeps the two in sync). AI only writes the short narratives marked `ai-suggested`, from the computed results, and never changes a score.

| Section | What it answers | Code | Rubric |
|---|---|---|---|
| Security posture | how secure is it today and after the move, what is reachable from the internet | `sovereign_shift/assess/posture.py` | [assess-security-posture](../skills/assess-security-posture/SKILL.md) |
| Risk assessment | what could go wrong, how bad, what the move itself fixes or adds, is it ready | `sovereign_shift/assess/risk.py` | [assess-risk](../skills/assess-risk/SKILL.md) |
| Performance | same capacity or not, and what runs differently on Leaseweb | `sovereign_shift/assess/performance.py` | [assess-performance](../skills/assess-performance/SKILL.md) |
| Scaling | where it breaks, the next size up with its price, how to scale out, hard limits | `sovereign_shift/assess/scaling.py` | [assess-scaling](../skills/assess-scaling/SKILL.md) |

The report starts with an executive summary built from these: security grade before and after, highest risk before and after, compute cost, and a readiness verdict (ready, ready with conditions, not ready).

## What the sample store shows
`sovereign-shift all --from-snapshot testdata/clickops_inventory.json --no-ai --out out/store`:
- Security D (41) today, C (69) after: the generated setup closes SSH to the world, the public database and the open database port.
- Highest risk critical today, high after. 3 risks are resolved by the migration. Readiness: ready with conditions (data copy, self-managed database, re-checking the default Leaseweb firewall group).
- Two web servers behind the load balancer scale out. The database is a single point of failure. Next size for a web server: +37.39 EUR/month.

## Limits, said plainly
- Only evidence from the scan counts. Areas without data say "not assessed" (for example identity, when there's no IAM data).
- Performance compares capacity, not real load: utilisation metrics aren't scanned yet.
- Scores rank risks, they aren't probabilities or money figures.
