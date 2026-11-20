import { useEffect, useState } from "react";
import Landing from "./Landing.jsx";
import Report from "./Report.jsx";
import { ApiError, analyse, demo, isReport, scan } from "./api.js";
import { cloudName } from "./format.js";

function withWorkspace(result) {
  const report = { ...result.report };
  if (result.assessment_id && Object.keys(result.files ?? {}).length) report.workspace = { id: result.assessment_id, files: result.files };
  return report;
}

export default function App() {
  const [state, setState] = useState({ report: null, label: "", busy: false, error: "" });

  async function load(task, label) {
    setState((s) => ({ ...s, busy: true, error: "" }));
    try {
      const report = await task();
      if (!isReport(report)) throw new ApiError("This file isn't a Sovereign Shift inventory or report.");
      setState({ report, label, busy: false, error: "" });
      window.scrollTo(0, 0);
    } catch (error) {
      setState((s) => ({ ...s, busy: false, error: error instanceof ApiError ? error.message : "Something went wrong while building the report." }));
    }
  }

  const onScan = (form) => load(async () => withWorkspace(await scan(form)),
    `${cloudName(form.provider)} account, read ${new Date().toLocaleString("en-GB")}`);
  const onDemo = () => load(async () => withWorkspace(await demo()), "Demo shop, synthetic data");
  const onFile = (file) => load(async () => {
    let data;
    try { data = JSON.parse(await file.text()); } catch { throw new ApiError("This file isn't valid JSON."); }
    return Array.isArray(data?.resources) ? withWorkspace(await analyse(JSON.stringify(data))) : data;
  }, `From ${file.name}`);

  // open the demo straight away with /#demo (handy on stage)
  useEffect(() => { if (window.location.hash === "#demo") onDemo(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <Landing hidden={Boolean(state.report)} busy={state.busy} error={state.error}
        onScan={onScan} onFile={onFile} onDemo={onDemo} />
      {state.report && <Report report={state.report} label={state.label}
        onReset={() => setState({ report: null, label: "", busy: false, error: "" })} />}
    </>
  );
}
