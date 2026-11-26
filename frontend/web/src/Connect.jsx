import { useRef, useState } from "react";
import { AWS_REGIONS } from "./format.js";

const PROVIDERS = [
  { id: "aws", label: "AWS" },
  { id: "gcp", label: "Google Cloud" },
  { id: "azure", label: "Azure" },
  { id: "cloudflare", label: "Cloudflare" },
  { id: "file", label: "File" },
];

export default function Connect({ busy, error, onScan, onFile, onDemo }) {
  const [provider, setProvider] = useState("aws");
  const [useAi, setUseAi] = useState(true);
  const form = useRef(null);
  const file = useRef(null);

  function submit(event) {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(form.current));
    onScan({ ...data, provider, use_ai: useAi });
  }

  return (
    <>
      <section className="connect" aria-labelledby="connect-title">
        <h2 id="connect-title">Connect an account</h2>
        <div className="tabs" role="tablist" aria-label="Source">
          {PROVIDERS.map((p) => (
            <button key={p.id} role="tab" type="button" aria-selected={provider === p.id}
              className={provider === p.id ? "tab on" : "tab"} onClick={() => setProvider(p.id)}>
              {p.label}
            </button>
          ))}
        </div>

        {provider === "file" ? (
          <div className="file-pick">
            <p>Open an <code>inventory.json</code> from <code>sovereign-shift scan</code>, or a <code>report.json</code> from an earlier assessment.</p>
            <input ref={file} type="file" accept=".json,application/json" hidden
              onChange={(e) => { const [f] = e.target.files; if (f) onFile(f); e.target.value = ""; }} />
            <button className="primary" type="button" disabled={busy} onClick={() => file.current.click()}>Choose a file</button>
          </div>
        ) : (
          <form ref={form} onSubmit={submit} autoComplete="off" aria-busy={busy}>
            {provider === "aws" ? (
              <>
                <label>Access key ID<input name="access_key_id" required spellCheck="false" placeholder="AKIA…" pattern="(AKIA|ASIA)[A-Z0-9]{16}" /></label>
                <label>Secret access key<input name="secret_access_key" type="password" required spellCheck="false" /></label>
                <label><span>Session token <span className="optional">only for temporary keys</span></span><input name="session_token" type="password" spellCheck="false" /></label>
                <label>Region
                  <select name="region" defaultValue="eu-north-1">
                    {Object.entries(AWS_REGIONS).map(([code, city]) => <option key={code} value={code}>{city} ({code})</option>)}
                  </select>
                </label>
              </>
            ) : provider === "gcp" ? (
              <>
                <label>Project ID<input name="project_id" required spellCheck="false" pattern="[a-z][a-z0-9\-]{4,28}[a-z0-9]" placeholder="my-shop-prod" /></label>
                <label><span>Access token <span className="optional">from a Viewer account</span></span><input name="access_token" type="password" required spellCheck="false" /></label>
                <p className="hint">Get one with <code>gcloud auth print-access-token --impersonate-service-account=VIEWER_SA</code>. It expires after an hour.</p>
              </>
            ) : provider === "azure" ? (
              <>
                <label>Subscription ID<input name="subscription_id" required spellCheck="false" pattern="[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}" placeholder="00000000-0000-0000-0000-000000000000" /></label>
                <label>Tenant ID<input name="tenant_id" required spellCheck="false" pattern="[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}" /></label>
                <label><span>Client ID <span className="optional">service principal with the Reader role</span></span><input name="client_id" required spellCheck="false" pattern="[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}" /></label>
                <label>Client secret<input name="client_secret" type="password" required spellCheck="false" /></label>
                <p className="hint">Create one with <code>az ad sp create-for-rbac --role Reader --scopes /subscriptions/SUBSCRIPTION_ID</code>. It prints the tenant, client ID and secret.</p>
              </>
            ) : (
              <>
                <label>Account ID<input name="account_id" required spellCheck="false" pattern="[a-fA-F0-9]{32}" placeholder="32 hexadecimal characters" /></label>
                <label>Worker name<input name="worker_name" required spellCheck="false" pattern="[a-zA-Z0-9_\-]+" /></label>
                <label><span>API token <span className="optional">Worker metadata read-only</span></span><input name="api_token" type="password" required spellCheck="false" /></label>
              </>
            )}
            <label>Destination
              <select name="target_region" defaultValue="eu-west-3">
                <option value="eu-west-3">Leaseweb Amsterdam (EU)</option>
                <option value="eu-central-1">Leaseweb Frankfurt (EU)</option>
                <option value="">Closest to the source region</option>
              </select>
            </label>
            <label className="check">
              <input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} />
              <span>Add AI suggestions <span className="optional">Mistral, resource metadata only</span></span>
            </label>
            <button className="primary" type="submit" disabled={busy}>{busy ? "Generating the report…" : "Generate report"}</button>
          </form>
        )}

        {error && <p className="error" role="alert">{error}</p>}
        <p className="alt">No account at hand? <button className="link" type="button" disabled={busy} onClick={onDemo}>Open the demo shop</button></p>
      </section>
    </>
  );
}
