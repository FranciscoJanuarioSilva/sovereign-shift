# Cost assessment (for the slides)

Produced 2026-11-20 by running the real pipeline. Prices on both sides come from the providers' own price APIs, not from our estimates:
- **AWS:** AWS Pricing API, on-demand, region EU (Stockholm), Linux/shared (RDS: PostgreSQL single-AZ). USD converted at 0.92 EUR, 730 hours per month. No Savings Plans, discounts or taxes.
- **Leaseweb:** Public Cloud API snapshot taken 2026-11-20 (`data/leaseweb_catalog.json`), Amsterdam, EUR, hourly contract, no taxes.

Per-resource data for charts: `docs/cost-assessment.csv`. Regenerate everything with the commands at the bottom.

## 1. Headline: a realistically sized store
A small web shop as customers actually run it: 2 web servers behind a load balancer and 1 PostgreSQL database.

| Resource | On AWS | EUR/month | On Leaseweb | EUR/month | Difference |
|---|---|---:|---|---:|---:|
| web-1 | t3.large (2 vCPU / 8 GiB) | 58.03 | lsw.m6a.large (2 / 8) | 37.38 | -35.6% |
| web-2 | m6g.large (2 / 8, ARM) | 55.07 | lsw.m6a.large (2 / 8) | 37.38 | -32.1% |
| orders database | db.t3.medium (2 / 4) | 49.70 | lsw.c5.large (2 / 4) | 29.76 | -40.1% |
| **Compute total** | | **162.80** | | **104.52** | **-35.8%** |

That is **58.28 EUR less per month, 699.36 EUR per year**, for the same vCPU and RAM.
Notes: the AWS web-2 runs on ARM (Graviton), so its images and binaries must be rebuilt for x86. The database moves to a self-hosted PostgreSQL on a VM, so backups, patching and failover become the customer's job.

## 2. Our live demo account, as built
The scan of our real AWS account (Stockholm). It uses free-tier instance sizes.

| Resource | On AWS | EUR/month | On Leaseweb | EUR/month | Difference |
|---|---|---:|---|---:|---:|
| web-1 | t3.micro (2 vCPU / 1 GiB) | 7.25 | lsw.c6a.large (2 / 4) | 33.05 | +355.9% |
| web-2 | m7i-flex.large (2 / 8) | 68.34 | lsw.m6a.large (2 / 8) | 37.38 | **-45.3%** |
| orders-db | db.t4g.micro (2 / 1 GiB) | 10.75 | lsw.c5.large (2 / 4) | 29.76 | +176.8% |
| **Compute total** | | **86.34** | | **100.19** | +16.0% |

Don't present this one as a saving. Leaseweb's smallest type is 2 vCPU / about 4 GiB, so micro instances move to a bigger, pricier VM. The only like-for-like row, web-2, is **45% cheaper** on Leaseweb. The report flags the other two as over-provisioned.

## 3. Traffic is where Leaseweb wins
Not in the totals above. AWS charges for outbound internet traffic. Leaseweb includes 1 TB per month (pooled) and charges 2.20 EUR per extra TB.

| Outbound traffic / month | AWS (EUR) | Leaseweb (EUR) |
|---:|---:|---:|
| 1 TB | 74.52 | 0.00 |
| 2 TB | 157.32 | 2.20 |
| 5 TB | 405.72 | 8.80 |
| 10 TB | 819.72 | 19.80 |

AWS: 0.09 USD/GB in the first 10 TB tier in Stockholm (Pricing API), first 100 GB per month free. Leaseweb: from the website's Public Cloud pricing page (https://www.leaseweb.com/products-services/cloud/public-cloud/pricing), first tier. Check it for your region before quoting.

## 4. What is not in these numbers
Storage (EBS vs Leaseweb disks), load balancers, public IPs, backups, support plans, data transfer between services, taxes, and any discounts or Savings Plans on either side. Leaseweb load balancer prices are not in the price API we use. Many newer Leaseweb types only have local NVMe disks (fast, not replicated), which the report notes per instance.

So: this is a **compute comparison with real list prices**, not an invoice. Say that on the slide.

## 5. Suggested slide wording
- "Loja de exemplo: 162,80 €/mês na AWS contra 104,52 € na Leaseweb. 36% menos, 699 € por ano, mesma capacidade."
- "Preços reais: API de preços da AWS e API da Leaseweb, não estimativas. Só computação, sem armazenamento, balanceadores nem impostos."
- "Tráfego: 5 TB/mês saem a 406 € na AWS e a 9 € na Leaseweb."
- Honest footnote: "Instâncias muito pequenas (micro) custam mais na Leaseweb porque o mínimo é 2 vCPU."

## 6. What an assessment costs us to run (AI, internal)
The end user never pays this and never needs a key. It's for the pitch Q&A ("what does it cost you per customer?").

Measured on 2026-11-20 with the real OpenRouter key, empty caches and AI on, using `mistralai/mistral-small-2603` (0.15 USD per million input tokens, 0.60 output), routed to Mistral:

| | Result |
|---|---|
| AI calls per assessment | 7 to 8 (runbook steps, firewall review, summary, plus one per unsupported service) |
| Cost per call | about **0.000025 USD** (2.5 thousandths of a cent) |
| Cost per assessment | about **0.0002 USD** (0.02 cents) |
| 1,000 assessments | about 0.19 USD |
| Rerun on the same input | **0 USD** and no network: answers are cached in `out/.cache/` |
| Run time with AI on | 10 to 12 seconds for the whole pipeline |
| Whole day so far (CI runs, tests, both measured runs) | 0.0019 USD of the 10 USD key limit |

- **Bigger model:** the docs suggest `mistral-medium-3-5` for the runbook agent and the reviewer. It costs 1.50 / 7.50 USD per million tokens, so 10 to 12 times more per call: still only about 0.002 USD per assessment. We run everything on the small model today because it was enough.
- **Why it's this cheap:** the AI never reads the whole account. It gets one resource at a time, redacted, and answers in a short JSON. All pricing, sizing, Terraform and firewall work is rules, which cost nothing.
- **Caveats:** only two runs were measured. OpenRouter's usage counter lags by several seconds, so I measured the pair together and divided. Cost grows with the number of unsupported services (one call each) and runbook-capable resources. Token counts per call weren't logged, so the bigger-model figure is a price-ratio estimate, not a measurement.
- **Pitch line:** "the AI part costs about two hundredths of a cent per assessment, and nothing at all when re-run."

## Reproduce
```bash
# live account, real prices on both sides (AWS prices need the read-only profile)
python scripts/fetch_aws_prices.py --profile sovereign-readonly --region eu-north-1 --inventory out/live/inventory.json
sovereign-shift all --profile sovereign-readonly --region eu-north-1 --out out/live
# the sample store
sovereign-shift all --from-snapshot testdata/clickops_inventory.json --no-ai --out out/store
# refresh Leaseweb prices (needs a Leaseweb token)
LEASEWEB_TOKEN=... python scripts/fetch_leaseweb_catalog.py
```
