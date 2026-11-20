import { DurableObject, WorkflowEntrypoint } from "cloudflare:workers";

export class Depot extends DurableObject {
  async bin() {
    const sql = this.ctx.storage.sql;
    sql.exec("CREATE TABLE IF NOT EXISTS bins (sku TEXT PRIMARY KEY, bin TEXT)");
    sql.exec("INSERT OR IGNORE INTO bins VALUES ('porto-blue', 'A-12')");
    return sql.exec("SELECT sku, bin FROM bins ORDER BY sku").toArray();
  }
}

export class Audit extends WorkflowEntrypoint {
  async run(event, step) {
    const stock = await step.do("count stock", () =>
      this.env.DB.prepare("SELECT sum(units) AS units FROM stock").first()
    );
    await step.do("queue audit", () =>
      this.env.EVENTS.send({ id: event.instanceId, units: stock.units })
    );
  }
}

async function authorized(request, expected) {
  if (!expected) return false;
  const encoder = new TextEncoder();
  const [suppliedHash, expectedHash] = await Promise.all(
    [request.headers.get("Authorization") || "", expected].map(value =>
      crypto.subtle.digest("SHA-256", encoder.encode(value))
    )
  );
  return crypto.subtle.timingSafeEqual(suppliedHash, expectedHash);
}

function migrationInventory(env) {
  const bindings = [
    ["DB", "d1", "shift-demo-catalog"],
    ["SETTINGS", "kv_namespace", "shift-demo-settings"],
    ["FILES", "r2_bucket", "shift-demo-assets"],
    ["DEPOT", "durable_object_namespace", "Depot"],
    ["EVENTS", "queue", "shift-demo-events"],
    ["AUDIT", "workflow", "shift-demo-audit"],
    ["ASSETS", "assets", "Stockroom static assets"]
  ];
  const worker = {
    id: "cf:worker:shift-demo",
    type: "cloudflare_worker",
    name: "shift-demo",
    region: "global",
    relations: []
  };
  const resources = [worker];
  for (const [binding, kind, name] of bindings) {
    if (!env[binding]) continue;
    const id = `cf:${kind}:${name}`;
    resources.push({ id, type: `cloudflare_${kind}`, name, region: "global" });
    worker.relations.push({ type: `binds_${binding}`, target: id });
  }
  return { source: "cloudflare", regions: ["global"], scanned_at: new Date().toISOString(), resources };
}

export default {
  async fetch(request, env) {
    const headers = { "Cache-Control": "private, no-store" };
    const path = new URL(request.url).pathname;
    if (path === "/api/migration") {
      const credential = env.MIGRATION_READ_KEY && "Bearer " + env.MIGRATION_READ_KEY;
      if (!await authorized(request, credential)) {
        return new Response("Authentication required", { status: 401, headers });
      }
      if (request.method !== "GET") {
        return new Response("Method not allowed", { status: 405, headers: { ...headers, Allow: "GET" } });
      }
      return Response.json(migrationInventory(env), { headers });
    }
    const catalogCredential = env.STOCKROOM_ACCESS_KEY && "Basic " + btoa("demo:" + env.STOCKROOM_ACCESS_KEY);
    if (!await authorized(request, catalogCredential)) {
      return new Response("Authentication required", {
        status: 401,
        headers: { ...headers, "WWW-Authenticate": 'Basic realm="Stockroom demo"' }
      });
    }
    if (path !== "/api/catalog") {
      const asset = await env.ASSETS.fetch(request);
      const response = new Response(asset.body, asset);
      response.headers.set("Cache-Control", headers["Cache-Control"]);
      return response;
    }
    const depot = env.DEPOT.getByName("lisbon");
    const [stock, settings, guide, bins, audits] = await Promise.all([
      env.DB.prepare("SELECT * FROM stock ORDER BY sku").all(),
      env.SETTINGS.get("catalog", "json"),
      env.FILES
        ? env.FILES.get("guide.txt")
        : env.ASSETS.fetch(new URL("/guide.txt", request.url)),
      depot.bin(),
      env.DB.prepare("SELECT * FROM audits ORDER BY id DESC LIMIT 5").all()
    ]);
    return Response.json({ stock: stock.results, settings, guide: await guide?.text(), bins, audits: audits.results }, { headers });
  },
  async scheduled(controller, env) {
    await env.AUDIT.create({ id: "stock-" + controller.scheduledTime });
  },
  async queue(batch, env) {
    const insert = env.DB.prepare("INSERT OR REPLACE INTO audits VALUES (?, ?)");
    await env.DB.batch(batch.messages.map(({ body }) => insert.bind(body.id, body.units)));
  }
};
