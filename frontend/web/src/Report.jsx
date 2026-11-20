import { useMemo, useState } from "react";
import Terraform from "./Terraform.jsx";
import { AWS_REGIONS, LEASEWEB_REGIONS, SEVERITY, STATUS, cloudName, money } from "./format.js";

const SECTIONS = [
  ["summary", "Summary"], ["costs", "Costs"], ["security", "Security"], ["terraform", "Terraform"],
  ["work", "Migration work"], ["runbook", "Data runbook"], ["dependencies", "Dependencies"],
];

function Route({ report }) {
  const from = report.source.regions?.[0];
  const to = report.target.region;
  return (
    <div className="route" aria-label={`From ${cloudName(report.source.cloud)} ${from ?? ""} to Leaseweb ${to ?? ""}`}>
      <div className="end">
        <span className="who">{cloudName(report.source.cloud)}</span>
        <span className="where">{AWS_REGIONS[from] ?? from ?? "account"}</span>
        <span className="code-name">{from}</span>
      </div>
      <svg className="line" viewBox="0 0 400 40" preserveAspectRatio="none" aria-hidden="true">
        <path d="M2 30 C 140 30, 220 10, 398 10" />
      </svg>
      <div className="end to">
        <span className="who">Leaseweb</span>
        <span className="where">{LEASEWEB_REGIONS[to] ?? to}</span>
        <span className="code-name">{to}</span>
      </div>
    </div>
  );
}

function AiNote({ item, title }) {
  if (!item?.text) return null;
  return (
    <aside className="ai-note">
      <h3>{title} <span className="ai-tag">AI suggestion</span></h3>
      <p>{item.text}</p>
      {item.justification && <p className="why">{item.justification}</p>}
    </aside>
  );
}

function Readiness({ summary }) {
  const total = summary.resources || 1;
  return (
    <div className="ready">
      <div className="stack" role="img" aria-label={Object.keys(STATUS).map((k) => `${summary[k] ?? 0} ${STATUS[k].label.toLowerCase()}`).join(", ")}>
        {Object.keys(STATUS).map((k) => summary[k] ? <span key={k} className={`seg ${k}`} style={{ flexGrow: summary[k] / total }} /> : null)}
      </div>
      <dl className="legend">
        {Object.entries(STATUS).map(([k, s]) => (
          <div key={k} className={`item ${k}`}><dt>{s.label}</dt><dd><strong>{summary[k] ?? 0}</strong> {s.hint}</dd></div>
        ))}
      </dl>
    </div>
  );
}

function Costs({ cost }) {
  const lines = cost.lines ?? [];
  const both = lines.filter((l) => Number.isFinite(l.aws) && Number.isFinite(l.leaseweb));
  const sum = (k) => both.reduce((t, l) => t + l[k], 0);
  const aws = sum("aws"), lsw = sum("leaseweb"), top = Math.max(aws, lsw, 1);
  return (
    <>
      {both.length ? (
        <div className="compare">
          <div className="bar-row"><span>AWS</span><span className="bar aws" style={{ width: `${(aws / top) * 100}%` }} /><strong>{money(aws)}</strong></div>
          <div className="bar-row"><span>Leaseweb</span><span className="bar lsw" style={{ width: `${(lsw / top) * 100}%` }} /><strong>{money(lsw)}</strong></div>
          <p className="quiet">Monthly, for the {both.length} resources priced on both sides. Storage, traffic, public IPs and load balancers are not included yet{cost.unpriced_resources ? `, and ${cost.unpriced_resources} resources have no price` : ""}.</p>
        </div>
      ) : <p className="quiet">No resource has a price on both sides yet.</p>}
      <table>
        <thead><tr><th scope="col">Resource</th><th scope="col">On AWS</th><th scope="col">On Leaseweb</th><th scope="col" className="num">AWS</th><th scope="col" className="num">Leaseweb</th></tr></thead>
        <tbody>
          {lines.map((l) => (
            <tr key={l.source_id}>
              <td>{l.name ?? l.source_id}</td><td>{l.aws_type ?? ""}</td>
              <td>{l.leaseweb_type ?? ""}{l.oversized && <span className="flag" title="The smallest Leaseweb size is 2 vCPU">larger</span>}</td>
              <td className="num">{money(l.aws)}{l.aws_estimated ? "*" : ""}</td>
              <td className={`num ${Number.isFinite(l.aws) && l.leaseweb < l.aws ? "win" : ""}`}>{money(l.leaseweb)}{l.leaseweb_estimated ? "*" : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {(cost.assumptions ?? []).length > 0 && <details><summary>How prices were worked out</summary><ul>{cost.assumptions.map((a) => <li key={a}>{a}</li>)}</ul></details>}
    </>
  );
}

function Security({ findings, names }) {
  const [level, setLevel] = useState("");
  const counts = Object.fromEntries(SEVERITY.map((s) => [s, findings.filter((f) => f.severity === s).length]));
  const rank = (f) => { const i = SEVERITY.indexOf(f.severity); return i < 0 ? SEVERITY.length : i; };
  const shown = findings.filter((f) => !level || f.severity === level).sort((a, b) => rank(a) - rank(b));
  return (
    <>
      <div className="filters" role="group" aria-label="Filter by severity">
        <button type="button" className={level === "" ? "chip on" : "chip"} onClick={() => setLevel("")}>All {findings.length}</button>
        {SEVERITY.filter((s) => counts[s]).map((s) => (
          <button key={s} type="button" className={level === s ? `chip on sev-${s}` : `chip sev-${s}`} onClick={() => setLevel(s)}>{s[0].toUpperCase() + s.slice(1)} {counts[s]}</button>
        ))}
      </div>
      <ul className="findings">
        {shown.map((f, i) => (
          <li key={f.id + f.resource + i} className={`sev-${f.severity}`}>
            <span className="sev">{f.severity}</span>
            <div>
              <h3>{f.title ?? f.id}</h3>
              <p><span className="res">{names.get(f.resource) ?? f.resource}</span> {f.evidence}</p>
              {f.fixed_by_migration && <p className="fixed">Fixed by the generated Leaseweb setup</p>}
            </div>
            <span className="fid">{f.id}</span>
          </li>
        ))}
      </ul>
    </>
  );
}

function Runbook({ runbook, names }) {
  const entries = runbook.entries.filter((e) => e.steps.length);
  if (!entries.length) return <p className="quiet">No data needs to move.</p>;
  return entries.map((e) => (
    <details key={e.source_id} className="rb">
      <summary><strong>{names.get(e.source_id) ?? e.source_id}</strong> {e.steps.length} {e.steps.length === 1 ? "step" : "steps"}{e.personalised && <span className="ai-tag">AI suggestion</span>}</summary>
      <ol>
        {e.steps.map((s) => (
          <li key={s.id}>
            <h3>{s.title ?? s.id}</h3>
            {s.command && <pre className="code">{s.command}</pre>}
            {s.verify && <p className="quiet">Check: <code>{s.verify}</code></p>}
            {(s.notes ?? []).map((n) => <p key={n} className="note">{n}</p>)}
          </li>
        ))}
      </ol>
    </details>
  ));
}

export default function Report({ report, label, onReset }) {
  const names = useMemo(() => new Map(report.graph.nodes.map((n) => [n.id, n.name])), [report]);
  const s = report.summary;
  return (
    <div className="report">
      <nav className="side" aria-label="Report sections">
        <a className="brand" href="#summary">Sovereign Shift</a>
        {SECTIONS.map(([id, text]) => <a key={id} href={`#${id}`}>{text}</a>)}
        <button type="button" className="secondary" onClick={onReset}>Assess another account</button>
      </nav>
      <main id="main">
        <header id="summary" className="head">
          <p className="label">{label}</p>
          <Route report={report} />
          <h1>{s.auto} of {s.resources} resources migrate automatically.</h1>
          <Readiness summary={s} />
          <AiNote item={report.explainer} title="What this migration involves" />
        </header>

        <section id="costs"><h2>Monthly cost</h2><Costs cost={report.cost} /></section>

        <section id="security">
          <h2>Security findings</h2>
          <p className="quiet">Problems found while reading the account. The network ones are closed in the generated setup.</p>
          <AiNote item={report.reviewer} title="Firewall review" />
          <Security findings={report.findings} names={names} />
        </section>

        <section id="terraform"><h2>Terraform for Leaseweb</h2><Terraform workspace={report.workspace} /></section>

        <section id="work">
          <h2>Migration work</h2>
          <table>
            <thead><tr><th scope="col">Resource</th><th scope="col">Status</th><th scope="col">What happens</th></tr></thead>
            <tbody>
              {report.work.map((w, i) => (
                <tr key={w.source_id + i}><td>{names.get(w.source_id) ?? w.source_id}</td><td><span className={`pill ${w.status}`}>{STATUS[w.status]?.label ?? w.status}</span></td><td>{w.what}</td></tr>
              ))}
            </tbody>
          </table>
        </section>

        <section id="runbook"><h2>Data runbook</h2><p className="quiet">Terraform rebuilds the infrastructure. These steps move the data. Values in angle brackets are filled in by your team.</p><Runbook runbook={report.runbook} names={names} /></section>

        <section id="dependencies">
          <h2>Dependencies</h2>
          <table>
            <thead><tr><th scope="col">From</th><th scope="col">To</th><th scope="col">Link</th><th scope="col">Source</th></tr></thead>
            <tbody>
              {report.graph.edges.map((e, i) => (
                <tr key={i} className={e.inferred ? "inferred" : ""}>
                  <td>{names.get(e.from) ?? e.from}</td><td>{names.get(e.to) ?? e.to}</td><td>{(e.type ?? "").replaceAll("_", " ")}</td>
                  <td>{e.inferred ? `Inferred: ${e.evidence ?? "from firewall rules"}` : "Read from the account"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
        <footer>Generated on this machine. Share the files in <code>public/</code> only, where the account id is masked.</footer>
      </main>
    </div>
  );
}
