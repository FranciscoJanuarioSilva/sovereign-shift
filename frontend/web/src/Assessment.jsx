import { money } from "./format.js";

const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : "");

export function AiNarrative({ section, title }) {
  const n = section?.narrative;
  if (!n?.text) return null;
  return <aside className="ai-note"><h3>{title} <span className="ai-tag">AI suggestion</span></h3><p>{n.text}</p></aside>;
}

function Ring({ score, grade, label, tone }) {
  const r = 46, c = 2 * Math.PI * r, pct = Math.max(0, Math.min(100, score ?? 0)) / 100;
  return (
    <figure className={`ring ${tone}`}>
      <svg viewBox="0 0 120 120" aria-hidden="true">
        <circle cx="60" cy="60" r={r} className="ring-track" />
        <circle cx="60" cy="60" r={r} className="ring-fill" strokeDasharray={`${c * pct} ${c}`} transform="rotate(-90 60 60)" />
        <text x="60" y="66" textAnchor="middle" className="ring-grade">{grade}</text>
      </svg>
      <figcaption><strong>{score}</strong>/100 {label}</figcaption>
    </figure>
  );
}

export function Posture({ posture }) {
  const o = posture.overall ?? {};
  return (
    <>
      <div className="posture-top">
        <Ring score={o.before} grade={o.grade_before} label="on AWS today" tone="before" />
        <span className="ring-arrow" aria-hidden="true">▸</span>
        <Ring score={o.after} grade={o.grade_after} label="on Leaseweb" tone="after" />
        <div className="domains">
          {(posture.domains ?? []).filter((d) => d.assessed).map((d) => (
            <div key={d.id} className="domain">
              <div className="domain-head"><span>{d.title}</span><span className="quiet">{d.fixed} of {d.findings} findings fixed</span></div>
              <div className="pair"><span className="b" style={{ width: `${d.before}%` }} /><em>{d.before}</em></div>
              <div className="pair"><span className="a" style={{ width: `${d.after}%` }} /><em>{d.after}</em></div>
            </div>
          ))}
          <p className="legend-inline"><span className="sw b" />AWS today <span className="sw a" />Leaseweb</p>
        </div>
      </div>
      <div className="exposure">
        {["before", "after"].map((when) => (
          <div key={when} className={`expo ${when}`}>
            <h3>{when === "before" ? "Reachable from the internet today" : "Still reachable after the move"}</h3>
            <ul>
              {(posture.exposure?.[when] ?? []).map((e) => (
                <li key={e.resource + e.how}><strong>{e.name}</strong> {e.how}{e.ports?.length ? <code>{e.ports.join(", ")}</code> : null}</li>
              ))}
              {!(posture.exposure?.[when] ?? []).length && <li className="quiet">Nothing</li>}
            </ul>
          </div>
        ))}
      </div>
    </>
  );
}

const band = (score) => (score >= 20 ? "critical" : score >= 12 ? "high" : score >= 6 ? "medium" : "low");

function Heatmap({ grid }) {
  return (
    <figure className="heat">
      <div className="heat-grid" role="table" aria-label="Risks by likelihood (rows, 5 at the top) and impact (columns)">
        {grid.map((row, i) => row.map((n, j) => {
          const score = (5 - i) * (j + 1);
          return <span key={`${i}-${j}`} role="cell" className={`cell ${band(score)} ${n ? "has" : ""}`} title={`likelihood ${5 - i}, impact ${j + 1}: ${n} risks`}>{n || ""}</span>;
        }))}
      </div>
      <figcaption><span>Likelihood ↑</span><span>Impact →</span></figcaption>
    </figure>
  );
}

function RiskList({ items, after }) {
  return (
    <ul className="risks">
      {items.map((r) => {
        const rating = after ? r.rating_after : r.rating;
        return (
          <li key={r.id}>
            <span className={`score ${rating}`}>{after ? r.score_after ?? "–" : r.score}</span>
            <strong title={r.mitigation}>{r.title}</strong>
            {!after && r.mitigated_by_migration && <span className="tag-ok">fixed</span>}
          </li>
        );
      })}
    </ul>
  );
}

export function Risk({ risk }) {
  const o = risk.overall ?? {};
  return (
    <>
      <div className="risk-top">
        <Heatmap grid={risk.heatmap ?? []} />
        <dl className="risk-facts">
          <div><dt>Risk today</dt><dd><span className={`pill-r ${o.current}`}>{cap(o.current)}</span></dd></div>
          <div><dt>After the move</dt><dd><span className={`pill-r ${o.after_migration}`}>{cap(o.after_migration)}</span></dd></div>
          <div><dt>Resolved by the move</dt><dd><strong>{o.resolved_by_migration}</strong> risks</dd></div>
          <div><dt>Readiness</dt><dd><span className={`verdict-pill ${String(o.readiness).replaceAll(" ", "-")}`}>{cap(o.readiness)}</span></dd></div>
        </dl>
      </div>
      <div className="two-col">
        <div><h3>Top risks today</h3><RiskList items={risk.top_today ?? []} /></div>
        <div><h3>Top risks after the move</h3><RiskList items={risk.top_after_migration ?? []} after /></div>
      </div>
    </>
  );
}

function Meter({ aws, lsw, unit, max }) {
  return (
    <div className="meter">
      <div><span className="b" style={{ width: `${(aws / max) * 100}%` }} /><em>{aws} {unit}</em></div>
      <div><span className="a" style={{ width: `${(lsw / max) * 100}%` }} /><em>{lsw} {unit}</em></div>
    </div>
  );
}

export function Performance({ performance }) {
  const rows = performance.rows ?? [];
  const maxCpu = Math.max(1, ...rows.flatMap((r) => [r.aws_vcpu, r.leaseweb_vcpu]));
  const maxMem = Math.max(1, ...rows.flatMap((r) => [r.aws_memory_gib, r.leaseweb_memory_gib]));
  return (
    <>
      <div className="perf">
        {rows.map((r) => (
          <article key={r.resource} className="perf-row">
            <div className="perf-name"><strong>{r.name}</strong><span className="quiet">{r.aws_type} ▸ {r.leaseweb_type}</span></div>
            <div><span className="quiet small">vCPU</span><Meter aws={r.aws_vcpu} lsw={r.leaseweb_vcpu} unit="" max={maxCpu} /></div>
            <div><span className="quiet small">Memory</span><Meter aws={r.aws_memory_gib} lsw={r.leaseweb_memory_gib} unit="GiB" max={maxMem} /></div>
            {(r.notes ?? []).length > 0 && <details className="perf-notes"><summary>{r.notes.length} {r.notes.length === 1 ? "note" : "notes"}</summary><ul>{r.notes.map((n) => <li key={n.note} className={n.severity}>{n.note}</li>)}</ul></details>}
          </article>
        ))}
      </div>
      <p className="legend-inline"><span className="sw b" />AWS <span className="sw a" />Leaseweb</p>
      {[...(performance.general ?? []), ...(performance.not_assessed ?? [])].length > 0 && (
        <details><summary>What else changes</summary>{[...(performance.general ?? []), ...(performance.not_assessed ?? [])].map((t) => <p key={t} className="note-line">{t}</p>)}</details>
      )}
    </>
  );
}

export function Scaling({ scaling }) {
  return (
    <>
      <div className="tiers">
        {(scaling.tiers ?? []).map((t) => (
          <article key={t.tier} className={`tier ${t.horizontal ? "h" : "v"}`}>
            <div className="servers" aria-hidden="true">{Array.from({ length: Math.min(t.servers, 6) }, (_, i) => <span key={i} />)}{t.horizontal && <span className="add">+</span>}</div>
            <h3>{t.tier}</h3>
            <p className="quiet">{t.kind}, {t.servers} {t.servers === 1 ? "server" : "servers"}</p>
            <p title={t.how}>{t.how.split(/:\s|;\s/)[0]}</p>
          </article>
        ))}
      </div>
      {(scaling.single_points_of_failure ?? []).map((s) => (
        <p key={s.what} className="spof"><strong>Single point of failure: {s.what}.</strong> {s.why}</p>
      ))}
      <div className="two-col">
        <div>
          <h3>Next size up</h3>
          <table>
            <thead><tr><th scope="col">Server</th><th scope="col">To</th><th scope="col" className="num">Extra per month</th></tr></thead>
            <tbody>{(scaling.scale_up ?? []).map((u) => (
              <tr key={u.resource}><td>{u.resource}<span className="quiet small block">{u.from}</span></td><td>{u.to}<span className="quiet small block">{u.vcpu} vCPU, {u.memory_gib} GiB</span></td><td className="num">{money(u.extra_eur_month)}</td></tr>
            ))}</tbody>
          </table>
        </div>
        <div>
          <h3>Adding servers</h3>
          <ol className="steps">{(scaling.scale_out ?? []).map((s) => <li key={s} title={s}>{s.split(/\s\(|:\s/)[0].replace(/\.$/, "")}</li>)}</ol>
        </div>
      </div>
      <details><summary>Platform limits to know</summary><ul>{(scaling.limits ?? []).map((l) => <li key={l.limit}>{l.limit}</li>)}</ul></details>
    </>
  );
}
