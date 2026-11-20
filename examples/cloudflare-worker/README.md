# Lisbon stockroom

This Worker serves a small stock catalog. D1 holds two products, KV holds the warehouse settings, R2 holds dispatch instructions, and a SQLite-backed Durable Object stores a bin assignment. A static landing page links to the catalog. A daily cron starts a Workflow that counts stock and sends the result to a Queue. The Worker consumes the message and saves the audit in D1.

## Run locally

From this folder with Node 22.12+ and npm installed, run

```sh
npm ci
npm run seed
npm run dev
```

Set `DEMO_PASSWORD` in a local, ignored `.dev.vars` file before starting the Worker. Open `http://localhost:8787/` and sign in as `demo` using that password. To exercise the daily audit immediately in the local simulator, run

```sh
curl -fsS -u demo http://localhost:8787/api/catalog
curl -fsS 'http://localhost:8787/cdn-cgi/handler/scheduled?cron=0+9+*+*+*'
```

Read the catalog again after the queue consumer runs. The stock totals 18 units and the newest audit records that total. Seeding can be repeated. Local state lives under `.wrangler/`.

## Assess the sample

From the repository root, run

```sh
sovereign-shift all --from-snapshot examples/cloudflare-worker/sample_snapshot.json --no-ai --out out/cloudflare-demo
```

The synthetic snapshot includes the Worker and its dependencies plus an example DNS zone. Two DNS-only A records share a Leaseweb record set. A proxied record requires manual review. Remove `--no-ai` to request alternatives for the Worker and other unmapped resources.

## Free-tier scope

The demo exercises the scanner's supported, locally reproducible Workers Free compute, storage and messaging services. It runs with synthetic IDs and local data, without a Cloudflare account. A hosted deployment needs real D1 and KV IDs, the named queue and R2 bucket, and separately seeded remote data. Live R2 requires activation and charges can apply beyond the Standard free allowance. DNS in the snapshot is synthetic and requires no domain purchase.

Cloudflare plan references checked 2026-11-20. [Workers and storage pricing](https://developers.cloudflare.com/workers/platform/pricing/) · [R2 pricing](https://developers.cloudflare.com/r2/pricing/) · [Durable Objects pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/) · [Queues pricing](https://developers.cloudflare.com/queues/platform/pricing/) · [Workflows pricing](https://developers.cloudflare.com/workflows/reference/pricing/).

## Host a protected demo

Replace the synthetic D1 and KV IDs with your demo resource IDs and provision the named Queue and a private R2 bucket. Seed the hosted stores with the files in `data/`. Set `DEMO_PASSWORD` as a Worker secret in Cloudflare or run `npx wrangler secret put DEMO_PASSWORD` and enter a generated ASCII password when prompted. The Worker requires it for the page and API. Use HTTPS and share the password separately from the URL. Keep API tokens, object-store keys and real customer data outside the demo.

A protected `workers.dev` URL works. For a custom hostname, set up the Worker custom domain and disable `workers_dev`. Preview URLs are disabled in the demo config. Use a separate read-only Cloudflare API token for migration inventory and separate scoped credentials for any authorized data transfer.

[Worker secrets](https://developers.cloudflare.com/workers/configuration/secrets/) · [Worker routes](https://developers.cloudflare.com/workers/configuration/routing/)
