import GitHubLink from "./GitHubLink.jsx";
import Connect from "./Connect.jsx";
import HeroGraphic from "./HeroGraphic.jsx";
import EuropeMap from "./EuropeMap.jsx";
import { AiFlow, FixDiagram, InferDiagram, Pipeline, SizeDiagram } from "./Diagrams.jsx";

export default function Landing({ hidden, ...props }) {
  return (
    <main id={hidden ? undefined : "main"} className="landing" hidden={hidden}>
      <section className="hero">
        <nav className="topnav" aria-label="Page">
          <a className="brand" href="#main"><svg viewBox="0 0 32 32" aria-hidden="true"><rect width="32" height="32" rx="7" /><path d="M7 22 C13 22 13 10 25 10" /></svg>Sovereign Shift</a>
          <div><a href="#how">How it works</a><a href="#ai">The AI</a><a href="#connect">Try it</a></div>
          <GitHubLink />
        </nav>
        <div className="hero-copy">
          <h1>Your AWS account, rebuilt on Leaseweb.</h1>
          <p className="lede">Paste a read-only key. Get Terraform, security fixes and a plan to move the data.</p>
          <div className="hero-actions">
            <a className="cta" href="#connect">Connect an account</a>
            <button className="cta ghost" type="button" disabled={props.busy} onClick={props.onDemo}>{props.busy ? "Building the report…" : "Open the demo shop"}</button>
          </div>
          {props.error && <p className="error" role="alert">{props.error}</p>}
        </div>
        <HeroGraphic />
        <a className="scroll-hint" href="#how">See how it works</a>
      </section>

      <section id="how" className="band">
        <div className="band-head">
          <h2>Six steps, all of them checkable</h2>
          <p>Each step writes a file the next one reads.</p>
        </div>
        <Pipeline />
      </section>

      <section className="band-dark">
        <div className="band split map-band">
          <div className="band-head">
            <h2>Bring it home to Europe</h2>
            <p>From AWS N. Virginia to Leaseweb Amsterdam, a Dutch-headquartered provider.</p>
            <dl className="stats">
              <div><dt>Destination</dt><dd>Amsterdam or Frankfurt</dd></div>
              <div><dt>AI inference</dt><dd>Mistral, France</dd></div>
              <div><dt>Runs in</dt><dd>this web app</dd></div>
            </dl>
          </div>
          <EuropeMap />
        </div>
      </section>

      <section id="ai" className="band split">
        <div className="band-head">
          <h2>Rules first. AI fills the gaps.</h2>
          <p>Rules write the Terraform. Mistral only answers what no rule covers, and every answer is validated.</p>
          <ul className="facts">
            <li>Never writes Terraform or commands</li>
            <li>Sees metadata, never secrets</li>
            <li>Every suggestion is marked</li>
          </ul>
        </div>
        <AiFlow />
      </section>

      <section className="band">
        <div className="band-head"><h2>Three simple algorithms</h2></div>
        <div className="algos">
          <article className="algo">
            <div><h3>Finding the links nobody wrote down</h3>
              <p>The database firewall admits the web servers, so they talk to it. The link is added and marked as inferred.</p></div>
            <InferDiagram />
          </article>
          <article className="algo">
            <div><h3>Choosing the closest Leaseweb size</h3>
              <p>Same family, at least the same vCPU and RAM, priced from the live Leaseweb catalog.</p></div>
            <SizeDiagram />
          </article>
          <article className="algo">
            <div><h3>Fixing what was open by accident</h3>
              <p>SSH and database ports open to the internet are closed down to who needs them.</p></div>
            <FixDiagram />
          </article>
        </div>
      </section>

      <section id="connect" className="band connect-band">
        <div className="band-head">
          <h2>Try it on your account</h2>
          <ul className="facts">
            <li><strong>Keys stay on this machine.</strong> Never saved, logged or sent to the AI.</li>
            <li><strong>Write access is refused.</strong> Use ReadOnlyAccess.</li>
            <li><strong>About 20 seconds</strong> for a small account.</li>
          </ul>
        </div>
        <Connect {...props} />
      </section>
      <footer className="landing-foot">Open source under Apache-2.0.</footer>
    </main>
  );
}
