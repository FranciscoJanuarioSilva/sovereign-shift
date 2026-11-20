// talks to frontend/serve.py on the same origin, nothing else
export class ApiError extends Error {}

async function post(path, payload) {
  let response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: typeof payload === "string" ? payload : JSON.stringify(payload),
    });
  } catch {
    throw new ApiError("The local server isn't running. Start it with: python frontend/serve.py --port 8001");
  }
  const result = await response.json().catch(() => null);
  if (!response.ok || !result) throw new ApiError(result?.error ?? "The local server returned an error. Check its terminal.");
  return result;
}

export const scan = (form) => post("/scan", form);
export const analyse = (inventoryText) => post("/analyse", inventoryText);
export const validate = (assessmentId) => post("/validate", { assessment_id: assessmentId });

export async function demo() {
  const response = await fetch("/demo-inventory.json");
  if (!response.ok) throw new ApiError("The demo inventory is missing from this checkout.");
  return analyse(await response.text());
}

export function isReport(raw) {
  const list = (v) => Array.isArray(v) && v.every((x) => x && typeof x === "object");
  return Boolean(raw && raw.source && raw.target && Number.isInteger(raw.summary?.resources) &&
    list(raw.cost?.lines) && list(raw.graph?.nodes) && list(raw.graph?.edges) &&
    list(raw.findings) && list(raw.work) && list(raw.runbook?.entries));
}
