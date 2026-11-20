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

async function authorized(request, password) {
  if (!password) return false;
  const expected = "Basic " + btoa("demo:" + password);
  const encoder = new TextEncoder();
  const [suppliedHash, expectedHash] = await Promise.all(
    [request.headers.get("Authorization") || "", expected].map(value =>
      crypto.subtle.digest("SHA-256", encoder.encode(value))
    )
  );
  return crypto.subtle.timingSafeEqual(suppliedHash, expectedHash);
}

export default {
  async fetch(request, env) {
    const headers = { "Cache-Control": "private, no-store" };
    if (!await authorized(request, env.DEMO_PASSWORD)) {
      return new Response("Authentication required", {
        status: 401,
        headers: { ...headers, "WWW-Authenticate": 'Basic realm="Stockroom demo"' }
      });
    }
    if (new URL(request.url).pathname !== "/api/catalog") {
      const asset = await env.ASSETS.fetch(request);
      const response = new Response(asset.body, asset);
      response.headers.set("Cache-Control", headers["Cache-Control"]);
      return response;
    }
    const depot = env.DEPOT.getByName("lisbon");
    const [stock, settings, guide, bins, audits] = await Promise.all([
      env.DB.prepare("SELECT * FROM stock ORDER BY sku").all(),
      env.SETTINGS.get("catalog", "json"),
      env.FILES.get("guide.txt"),
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
