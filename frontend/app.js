"use strict";

const byId = (id) => document.getElementById(id);
const money = new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR" });
const percentage = new Intl.NumberFormat("en-IE", { style: "percent", maximumFractionDigits: 1 });
const levels = { critical: "Critical", high: "High", medium: "Medium", low: "Low", info: "Informational", warning: "Warning" };
const statuses = { auto: "Automatic", partial: "Partial", manual: "Manual", unsupported: "Unsupported" };
const filePicker = byId("report-file");
let activeReport;
let previousReport;
let loadVersion = 0;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function table(container, headers, rows, empty) {
  container.replaceChildren();
  if (!rows.length) {
    container.append(element("p", empty));
    return;
  }
  const shell = element("div", null, "table-wrap");
  const grid = element("table");
  const header = grid.createTHead().insertRow();
  for (const label of headers) {
    const heading = element("th", label);
    heading.scope = "col";
    header.append(heading);
  }
  const body = grid.createTBody();
  for (const row of rows) {
    const entry = body.insertRow();
    for (const value of row) entry.insertCell().textContent = value;
  }
  shell.append(grid);
  container.append(shell);
}

function nameOf(report, id) {
  return report.names.get(id) ?? id ?? "—";
}

function amount(value, estimate = false) {
  if (!Number.isFinite(value)) return "Unknown";
  return money.format(value) + (estimate ? " (estimate)" : "");
}

function bar(label, value, share, variant) {
  const row = element("div", null, "chart-row");
  const heading = element("div", null, "chart-label");
  heading.append(element("span", label), element("strong", value));
  const track = element("div", null, "chart-track");
  track.setAttribute("aria-hidden", "true");
  const fill = element("div", null, "chart-fill " + variant);
  fill.style.width = Math.min(100, Math.max(0, share * 100)) + "%";
  track.append(fill);
  row.append(heading, track);
  return row;
}

function renderCostComparison(lines) {
  const comparison = byId("cost-comparison");
  comparison.replaceChildren(element("h3", "Matched monthly costs"));
  const matched = lines.filter((line) => Number.isFinite(line.aws) && Number.isFinite(line.leaseweb));
  if (!matched.length) {
    comparison.append(element("p", "No resources have prices from both providers."));
    return;
  }

  const total = (provider) => matched.reduce((sum, line) => sum + Math.round(line[provider] * 100), 0);
  const aws = total("aws");
  const leaseweb = total("leaseweb");
  const scale = Math.max(aws, leaseweb, 1);
  const diff = leaseweb - aws;
  let headline = "Both providers have the same matched monthly cost.";
  if (diff) {
    const direction = diff < 0 ? "lower" : "higher";
    const share = aws > 0 ? " (" + percentage.format(Math.abs(diff) / aws) + ")" : "";
    headline = "Leaseweb is " + amount(Math.abs(diff) / 100) + "/month " + direction + share + ".";
  }
  comparison.append(
    element("p", headline, "comparison-result"),
    bar("AWS", amount(aws / 100), aws / scale, "aws"),
    bar("Leaseweb", amount(leaseweb / 100), leaseweb / scale, "leaseweb"),
  );
}

function renderReadiness(report) {
  const chart = byId("readiness-chart");
  chart.replaceChildren();
  const total = report.summary.resources;
  for (const [status, label] of Object.entries(statuses)) {
    const count = report.summary[status] ?? 0;
    const share = total > 0 ? count / total : 0;
    chart.append(bar(label, count + " of " + total + " (" + percentage.format(share) + ")", share, status));
  }
  const links = report.graph.edges.filter((edge) => edge.inferred).length;
  const findings = report.findings.length;
  byId("readiness-note").textContent =
    "The assessment surfaced " + findings + (findings === 1 ? " security finding" : " security findings") +
    " and inferred " + links + (links === 1 ? " dependency." : " dependencies.") +
    " Automatic refers to the proposed migration work.";
}

function renderCosts(report, demo) {
  byId("cost-source").textContent = demo
    ? "Synthetic demo data with illustrative prices from the project catalogs."
    : "Prices come from catalog references and estimates. Billing data was not used.";
  const container = byId("cost-cards");
  container.replaceChildren();
  const unpriced = report.cost.unpriced_resources ?? 0;
  let incomplete = unpriced > 0;
  for (const [provider, label] of [["aws", "AWS"], ["leaseweb", "Leaseweb"]]) {
    const lines = report.cost.lines;
    const count = lines.filter((line) => Number.isFinite(line[provider])).length;
    const subtotal = report.cost[provider + "_priced_subtotal_eur"];
    incomplete ||= count !== lines.length;
    const card = element("div");
    card.append(
      element("h3", label),
      element("strong", count ? amount(subtotal) : "No prices available"),
      element("p", count + " of " + (lines.length + unpriced) + " resources priced")
    );
    container.append(card);
  }
  byId("cost-note").textContent = incomplete
    ? "Some prices are missing. The subtotals do not establish which provider is cheaper."
    : "Monthly estimates are based on the assumptions in this report.";
  if (unpriced) byId("cost-note").textContent += " " + unpriced + " resources have no price on either side.";
  renderCostComparison(report.cost.lines);
  const assumptions = byId("cost-assumptions");
  assumptions.replaceChildren();
  for (const note of Array.isArray(report.cost.assumptions) ? report.cost.assumptions : []) {
    assumptions.append(element("li", note));
  }
  assumptions.parentElement.hidden = !assumptions.children.length;
  table(byId("cost-lines"), ["Resource", "AWS", "Leaseweb"], report.cost.lines.map((line) => [
    line.name ?? nameOf(report, line.source_id),
    amount(line.aws, line.aws_estimated),
    amount(line.leaseweb, line.leaseweb_estimated),
  ]), "No cost entries.");
}

function renderFindings() {
  const container = byId("findings");
  const selected = byId("severity").value;
  const findings = activeReport.findings.filter((finding) => !selected || finding.severity === selected);
  container.replaceChildren();
  if (!findings.length) container.append(element("p", "No findings match this filter."));
  for (const finding of findings) {
    const item = element("article", null, "finding");
    const badge = element("span", levels[finding.severity] ?? finding.severity ?? "Severity unavailable", "badge");
    badge.dataset.level = finding.severity ?? "";
    item.append(
      badge,
      element("h3", finding.title ?? finding.id),
      element("p", nameOf(activeReport, finding.resource)),
    );
    if (finding.evidence) item.append(element("p", finding.evidence));
    if (finding.fix) item.append(element("p", finding.fix));
    container.append(item);
  }
}

function renderRunbook(report) {
  const container = byId("runbook-items");
  container.replaceChildren();
  const entries = report.runbook.entries.filter((entry) => entry.steps.length);
  if (!entries.length) container.append(element("p", "This report has no migration steps."));
  for (const entry of entries) {
    const details = element("details");
    const summary = nameOf(report, entry.source_id) + " · " + entry.steps.length + (entry.steps.length === 1 ? " step" : " steps");
    details.append(element("summary", summary));
    const steps = element("ol");
    for (const step of entry.steps) {
      const item = element("li");
      item.append(element("h3", step.title ?? step.id));
      if (step.command) item.append(element("pre", step.command));
      if (step.verify) item.append(element("pre", step.verify));
      for (const note of step.notes ?? []) item.append(element("p", note));
      steps.append(item);
    }
    details.append(steps);
    container.append(details);
  }
  const unsupported = report.runbook.entries.filter((entry) => !entry.steps.length).length;
  if (unsupported) container.append(element("p", unsupported + " resources have no runbook steps. See Migration work for details."));
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isRecordList(value) {
  return Array.isArray(value) && value.every(isRecord);
}

function prepare(raw) {
  if (!isRecord(raw) || !isRecord(raw.source) || !isRecord(raw.target) ||
      !Number.isInteger(raw.summary?.resources) || !Array.isArray(raw.source.regions) ||
      !isRecordList(raw.cost?.lines) || !isRecordList(raw.graph?.nodes) ||
      !isRecordList(raw.graph?.edges) || !isRecordList(raw.findings) ||
      !isRecordList(raw.work) || !isRecordList(raw.runbook?.entries) ||
      !raw.runbook.entries.every((entry) => isRecordList(entry.steps) &&
        entry.steps.every((step) => step.notes == null || Array.isArray(step.notes)))) {
    throw new Error("This file is not a Sovereign Shift report.json.");
  }
  return { ...raw, names: new Map(raw.graph.nodes.map((node) => [node.id, node.name])) };
}

function showFile(workspace, name) {
  workspace.selected = name;
  byId("terraform-filename").textContent = name;
  byId("terraform-source").textContent = workspace.files[name];
  for (const button of byId("terraform-files").children) {
    button.setAttribute("aria-pressed", String(button.textContent === name));
  }
}

function showValidation(workspace) {
  const status = workspace?.validation;
  byId("validate-terraform").disabled = status?.pending ?? false;
  byId("validation-status").textContent = status?.message ?? "";
  byId("validation-output").textContent = status?.output ?? "";
  byId("validation-details").hidden = !status?.output;
  byId("validation-details").open = Boolean(status?.output && !status.passed);
}

function renderWorkspace(workspace) {
  byId("workspace-files").hidden = !workspace;
  byId("terraform-empty").hidden = Boolean(workspace);
  byId("validate-terraform").hidden = !workspace;
  showValidation(workspace);
  const list = byId("terraform-files");
  list.replaceChildren();
  if (!workspace) return;

  const names = Object.keys(workspace.files);
  for (const name of names) {
    const button = element("button", name, "secondary");
    button.type = "button";
    button.addEventListener("click", () => showFile(workspace, name));
    list.append(button);
  }
  showFile(workspace, workspace.selected ?? names[0]);
}

async function validateWorkspace() {
  const workspace = activeReport?.workspace;
  if (!workspace || workspace.validation?.pending) return;
  workspace.validation = { pending: true, message: "Running Terraform init and validate…" };
  showValidation(workspace);
  try {
    const result = await postJson("/validate", JSON.stringify({ assessment_id: workspace.id }));
    workspace.validation = {
      passed: result.passed,
      message: result.passed ? "Terraform validation passed." : "Terraform validation failed.",
      output: result.output,
    };
  } catch (error) {
    workspace.validation = { message: error.message || "Could not validate Terraform." };
  }
  if (activeReport?.workspace === workspace) showValidation(workspace);
}

function downloadFile() {
  const workspace = activeReport?.workspace;
  const name = workspace?.selected;
  if (!name) return;
  const url = URL.createObjectURL(new Blob([workspace.files[name]], {type: "text/plain;charset=utf-8"}));
  const link = element("a");
  link.href = url;
  link.download = name.split("/").at(-1);
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function render(report, label, demo) {
  activeReport = report;
  if (!demo) previousReport = { report, label };

  const demoButton = byId("open-demo");
  const backButton = byId("back-to-report");
  const focused = document.activeElement;
  demoButton.hidden = demo;
  backButton.hidden = !demo;
  backButton.textContent = previousReport ? "Back to report" : "Back to upload";
  if ([demoButton, byId("start-demo")].includes(focused) && !backButton.hidden) backButton.focus();
  if (focused === backButton && !demoButton.hidden) demoButton.focus();
  const region = report.source.regions.join(", ");
  const source = report.source.cloud === "aws" ? "AWS" : report.source.cloud;
  const target = report.target.cloud === "leaseweb" ? "Leaseweb" : report.target.cloud;
  byId("route").textContent = [source, region, target, report.target.region].filter(Boolean).join(" / ");
  byId("source-label").textContent = label;
  const metrics = byId("metrics");
  metrics.replaceChildren();
  for (const [text, value] of [
    ["Resources", report.summary.resources],
    ["Automatic", report.summary.auto],
    ["Partial", report.summary.partial],
    ["Manual or unsupported", (report.summary.manual ?? 0) + (report.summary.unsupported ?? 0)],
  ]) {
    const metric = element("div");
    metric.append(element("dt", text), element("dd", value ?? "—"));
    metrics.append(metric);
  }
  renderWorkspace(report.workspace);
  renderCosts(report, demo);
  renderReadiness(report);
  const severity = byId("severity");
  severity.replaceChildren(new Option("All", ""));
  const found = new Set(report.findings.map((finding) => finding.severity).filter(Boolean));
  for (const level of [...Object.keys(levels).filter((level) => found.delete(level)), ...found]) {
    severity.append(new Option(levels[level] ?? level, level));
  }
  renderFindings();
  table(byId("edges"), ["Source", "Target", "Relationship", "Evidence"], report.graph.edges.map((edge) => [
    nameOf(report, edge.from), nameOf(report, edge.to), (edge.type ?? "").replaceAll("_", " "),
    edge.inferred ? "Inferred" + (edge.evidence ? " · " + edge.evidence : "") : "Observed",
  ]), "No dependencies recorded.");
  table(byId("work"), ["Resource", "Status", "Action"], report.work.map((item) => [
    nameOf(report, item.source_id), statuses[item.status] ?? item.status ?? "—", item.what ?? "—",
  ]), "No migration work recorded.");
  renderRunbook(report);
  byId("empty-state").hidden = true;
  byId("dashboard").hidden = false;
}

function feedback(message, pending = false) {
  const box = byId("feedback");
  box.textContent = message;
  box.hidden = !message;
  box.classList.toggle("pending", pending);
}

async function loadReport(read, label, failure, demo = false, pending = "") {
  const version = ++loadVersion;
  feedback(pending, true);
  try {
    const result = await read();
    const report = prepare(result.report);
    if (result.assessment_id && Object.keys(result.files ?? {}).length) {
      report.workspace = { id: result.assessment_id, files: result.files };
    }
    if (version !== loadVersion) return;
    render(report, label, demo);
    feedback("");
  } catch (error) {
    if (version !== loadVersion) return;
    feedback(error instanceof UploadError ? error.message : failure);
    if (!activeReport) {
      byId("source-label").textContent = "Choose an AWS inventory or a migration report to get started.";
      byId("open-demo").hidden = false;
    }
  }
}

class UploadError extends Error {}

async function postJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  });
  const result = await response.json().catch(() => null);
  if (!response.ok || !result) {
    throw new UploadError(result?.error ?? "Start the local dashboard server to use this action.");
  }
  return result;
}

function loadDemo() {
  return loadReport(async () => {
    const response = await fetch("demo-inventory.json");
    if (!response.ok) throw new Error("Demo unavailable");
    return postJson("/analyse", await response.text());
  }, "Demo · synthetic data", "Could not load the demo. Start the local dashboard server.",
  true, "Analysing the demo inventory…");
}

async function readUpload(file) {
  let data;
  try {
    data = JSON.parse(await file.text());
  } catch {
    throw new UploadError("This file is not valid JSON.");
  }
  return data?.source === "aws" && Array.isArray(data.resources)
    ? postJson("/analyse", file)
    : { report: data };
}

byId("open-report").addEventListener("click", () => filePicker.click());
byId("open-demo").addEventListener("click", loadDemo);
byId("start-upload").addEventListener("click", () => filePicker.click());
byId("start-demo").addEventListener("click", loadDemo);
byId("validate-terraform").addEventListener("click", validateWorkspace);
byId("download-file").addEventListener("click", downloadFile);
byId("back-to-report").addEventListener("click", () => {
  ++loadVersion;
  feedback("");
  if (previousReport) {
    render(previousReport.report, previousReport.label, false);
    return;
  }
  activeReport = undefined;
  byId("dashboard").hidden = true;
  byId("empty-state").hidden = false;
  byId("source-label").textContent = "Choose an AWS inventory or a migration report to get started.";
  byId("route").textContent = "AWS / Leaseweb";
  byId("back-to-report").hidden = true;
  byId("open-demo").hidden = false;
  byId("open-report").focus();
});
byId("severity").addEventListener("change", renderFindings);
filePicker.addEventListener("change", () => {
  const [file] = filePicker.files;
  if (file) loadReport(() => readUpload(file), "Local assessment · " + file.name,
    "Could not open this file. Select an AWS inventory.json or a Sovereign Shift report.json.",
    false, "Reading " + file.name + "…");
  filePicker.value = "";
});
