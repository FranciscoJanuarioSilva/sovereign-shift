# Skill tree

`SKILL.md` files that teach an AI agent how to do one job in sovereign-shift. Each folder is one skill (Claude Code format: frontmatter `name` and `description`, then the instructions). Claude Code finds them through the `.claude/skills` link to this folder. Our own AI agents load the assessment skills at runtime with `sovereign_shift.skills.load(name)`.

The tree follows the pipeline. Start at the root and go down to the step you are working on.

```
sovereign-shift                     the product, the pipeline, the rules every skill inherits
├── scan-aws                        read-only AWS inventory
├── scan-azure                      Azure inventory (sample and mocks only, not live yet)
├── translate-leaseweb              AWS/Azure resources -> Leaseweb targets, sizing, prices
├── assess                          (group) scoring sections of the report, rules only
│   ├── assess-security-posture     domain scores before/after, internet exposure
│   ├── assess-risk                 likelihood x impact register, readiness verdict
│   ├── assess-performance          capacity parity and platform differences
│   ├── assess-scaling              tiers, single points of failure, scale up/out, limits
│   └── assess-cost                 real list prices on both sides, what is excluded
├── generate-terraform              Leaseweb Terraform from mapping.json
├── finalize-leaseweb               security groups and LB targets through the API
├── runbook                         data migration steps from templates
└── report                          report.md / report.json
```

| Skill | Use it when |
|---|---|
| [sovereign-shift](sovereign-shift/SKILL.md) | you start any work in this repo |
| [scan-aws](scan-aws/SKILL.md) | you change or run the AWS scanner |
| [scan-azure](scan-azure/SKILL.md) | you work on Azure as a source |
| [translate-leaseweb](translate-leaseweb/SKILL.md) | you change how a resource maps to Leaseweb |
| [assess-security-posture](assess-security-posture/SKILL.md) | you score or explain security |
| [assess-risk](assess-risk/SKILL.md) | you add, score or explain risks |
| [assess-performance](assess-performance/SKILL.md) | you compare performance before and after |
| [assess-scaling](assess-scaling/SKILL.md) | you explain how the result scales |
| [assess-cost](assess-cost/SKILL.md) | you touch prices or the cost table |
| [generate-terraform](generate-terraform/SKILL.md) | you change the generated Terraform |
| [finalize-leaseweb](finalize-leaseweb/SKILL.md) | you change or run finalize |
| [runbook](runbook/SKILL.md) | you add or change runbook templates |
| [report](report/SKILL.md) | you change what the report shows |

## Adding a skill
1. Make a folder named like the skill, with `SKILL.md` inside.
2. Frontmatter: `name` (equal to the folder) and `description` (one sentence: what it does and when to use it).
3. Sections: Part of, Inputs, Steps, Rules (or Rubric), Output, Pitfalls. Link to `docs/` instead of copying facts.
4. Add it to the tree and the table above. `tests/test_skills.py` checks all of this.
