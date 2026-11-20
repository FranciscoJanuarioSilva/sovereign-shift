// small schematic drawings for the landing page, plain svg so they stay sharp and light

export function Pipeline() {
  const steps = [
    ["Scan", "Read-only, every resource"],
    ["Graph", "Who talks to whom"],
    ["Translate", "Leaseweb equivalent for each"],
    ["Generate", "Terraform from templates"],
    ["Runbook", "How the data moves"],
    ["Report", "Cost, risks, work list"],
  ];
  return (
    <ol className="pipeline">
      {steps.map(([title, text], i) => (
        <li key={title}>
          <span className="pnum" aria-hidden="true">{i + 1}</span>
          <h3>{title}</h3>
          <p>{text}</p>
        </li>
      ))}
    </ol>
  );
}

export function AiFlow() {
  // boxes: [x, y, w, h], wide enough for their labels at 15px / 12px
  return (
    <svg className="diagram" viewBox="0 0 820 300" role="img" aria-label="Every resource goes to the rules first. Only what the rules can't map goes to the AI. The AI's answer is validated: valid answers reach the report marked as AI suggestions, invalid ones are dropped.">
      <defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0 L10 5 L0 10 z" className="arrowhead" /></marker></defs>
      <g className="box"><rect x="10" y="115" width="140" height="64" rx="8" /><text x="80" y="142" textAnchor="middle">Resource</text><text x="80" y="162" textAnchor="middle" className="small">from the scan</text></g>
      <g className="box rules"><rect x="225" y="30" width="200" height="64" rx="8" /><text x="325" y="57" textAnchor="middle">Rules</text><text x="325" y="77" textAnchor="middle" className="small">sizing, regions, firewall</text></g>
      <g className="box ai"><rect x="225" y="190" width="200" height="64" rx="8" /><text x="325" y="217" textAnchor="middle">AI (Mistral)</text><text x="325" y="237" textAnchor="middle" className="small">metadata only, no secrets</text></g>
      <g className="box guard"><rect x="480" y="190" width="160" height="64" rx="8" /><text x="560" y="217" textAnchor="middle">Validator</text><text x="560" y="237" textAnchor="middle" className="small">schema + templates</text></g>
      <g className="box out"><rect x="670" y="115" width="140" height="64" rx="8" /><text x="740" y="142" textAnchor="middle">Report</text><text x="740" y="162" textAnchor="middle" className="small">AI parts marked</text></g>
      <path d="M150 135 C 190 135, 190 62, 223 62" className="flow" markerEnd="url(#arr)" />
      <path d="M150 160 C 190 160, 190 222, 223 222" className="flow dashed" markerEnd="url(#arr)" />
      <text x="232" y="282" className="small">only when no rule fits</text>
      <path d="M425 62 C 560 62, 620 120, 668 135" className="flow" markerEnd="url(#arr)" />
      <path d="M425 222 L 478 222" className="flow" markerEnd="url(#arr)" />
      <path d="M640 212 C 660 195, 655 175, 668 162" className="flow ok" markerEnd="url(#arr)" />
      <path d="M560 254 L 560 276" className="flow bad" />
      <text x="572" y="282" className="small bad-text">invalid answer: dropped</text>
    </svg>
  );
}

export function InferDiagram() {
  return (
    <svg className="mini" viewBox="0 0 320 170" role="img" aria-label="db-sg allows port 5432 from web-sg, so web-1 and web-2 can reach the database: two inferred links.">
      <g className="m-node"><circle cx="50" cy="45" r="16" /><text x="50" y="80" textAnchor="middle">web-1</text></g>
      <g className="m-node"><circle cx="50" cy="125" r="16" /><text x="50" y="160" textAnchor="middle">web-2</text></g>
      <g className="m-node db"><circle cx="260" cy="85" r="20" /><text x="260" y="125" textAnchor="middle">orders</text></g>
      <path d="M68 47 C 150 40, 190 70, 238 80" className="m-edge" />
      <path d="M68 123 C 150 130, 190 100, 238 90" className="m-edge" />
      <rect x="96" y="72" width="128" height="26" rx="13" className="m-tag" /><text x="160" y="89" textAnchor="middle" className="m-tag-text">5432 from web-sg</text>
    </svg>
  );
}

export function SizeDiagram() {
  const rows = [["t3.micro", "2 vCPU", "1 GiB"], ["m7i-flex.large", "2 vCPU", "8 GiB"], ["db.t4g.micro", "2 vCPU", "1 GiB"]];
  const to = [["lsw.c6a.large", "2 / 4 GiB", true], ["lsw.m6a.large", "2 / 8 GiB", false], ["lsw.c5.large", "2 / 4 GiB", true]];
  return (
    <table className="size-map">
      <thead><tr><th scope="col">On AWS</th><th scope="col" aria-label="becomes" /><th scope="col">On Leaseweb</th></tr></thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={r[0]}>
            <td><strong>{r[0]}</strong> <span>{r[1]}, {r[2]}</span></td>
            <td className="arrow" aria-hidden="true">▸</td>
            <td><strong>{to[i][0]}</strong> <span>{to[i][1]}</span>{to[i][2] && <em>smallest size</em>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function FixDiagram() {
  return (
    <div className="fix">
      <div className="fix-col bad"><span>AWS rule</span><code>tcp/22 from 0.0.0.0/0</code><code>tcp/5432 from 0.0.0.0/0</code></div>
      <div className="fix-arrow" aria-hidden="true">▸</div>
      <div className="fix-col good"><span>Leaseweb rule</span><code>tcp/22 from your admin range</code><code>tcp/5432 from web_1, web_2 only</code></div>
    </div>
  );
}
