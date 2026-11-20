import { useState } from "react";
import { validate } from "./api.js";

function download(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain;charset=utf-8" }));
  const link = Object.assign(document.createElement("a"), { href: url, download: name.split("/").at(-1) });
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function Terraform({ workspace }) {
  const names = Object.keys(workspace?.files ?? {});
  const [selected, setSelected] = useState(names[0]);
  const [check, setCheck] = useState(null);

  if (!workspace) return <p className="quiet">This report was opened from a file, so the Terraform isn't attached. Connect the account or open the inventory to get it.</p>;

  async function run() {
    setCheck({ pending: true });
    try {
      const result = await validate(workspace.id);
      setCheck({ passed: result.passed, output: result.output });
    } catch (error) {
      setCheck({ error: error.message });
    }
  }

  const current = workspace.files[selected] ?? "";
  return (
    <div className="tf">
      <div className="tf-bar">
        <div className="tf-files" role="group" aria-label="Generated files">
          {names.map((name) => (
            <button key={name} type="button" aria-pressed={name === selected} className={name === selected ? "chip on" : "chip"} onClick={() => setSelected(name)}>{name}</button>
          ))}
        </div>
        <div className="tf-actions">
          <button type="button" className="secondary" onClick={() => download(selected, current)}>Download {selected.split("/").at(-1)}</button>
          <button type="button" className="secondary" disabled={check?.pending} onClick={run}>{check?.pending ? "Validating…" : "Validate with Terraform"}</button>
        </div>
      </div>
      {check && !check.pending && (
        <div className={check.passed ? "verdict ok" : "verdict bad"} role="status">
          {check.error ?? (check.passed ? "terraform validate passed." : "terraform validate found problems.")}
          {check.output && <details><summary>Terraform output</summary><pre>{check.output}</pre></details>}
        </div>
      )}
      <pre className="code" tabIndex={0}><code>{current}</code></pre>
    </div>
  );
}
