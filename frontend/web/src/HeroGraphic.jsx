// aws resources on the left, their leaseweb counterparts on the right, data packets travelling between them
const AWS = [
  { id: "alb", label: "web-alb", kind: "load balancer", x: 120, y: 70 },
  { id: "w1", label: "web-1", kind: "ec2", x: 60, y: 170 },
  { id: "w2", label: "web-2", kind: "ec2", x: 190, y: 175 },
  { id: "db", label: "orders", kind: "rds postgres", x: 120, y: 285 },
  { id: "s3", label: "assets", kind: "s3 bucket", x: 235, y: 330 },
  { id: "sg", label: "db-sg", kind: "security group", x: 40, y: 360 },
];
const LSW = [
  { id: "alb", label: "web_alb", kind: "load balancer", x: 670, y: 70 },
  { id: "w1", label: "web_1", kind: "instance", x: 610, y: 170 },
  { id: "w2", label: "web_2", kind: "instance", x: 740, y: 175 },
  { id: "db", label: "orders_db", kind: "instance + postgres 18", x: 670, y: 285 },
  { id: "s3", label: "assets", kind: "object storage", x: 760, y: 330 },
  { id: "sg", label: "db_sg", kind: "security group (api)", x: 590, y: 360 },
];
const LINKS = [["alb", "w1"], ["alb", "w2"], ["w1", "db"], ["w2", "db"], ["sg", "db"], ["w2", "s3"]];
const at = (side, id) => side.find((n) => n.id === id);

function Cluster({ nodes, side }) {
  return (
    <g className={`cluster ${side}`}>
      {LINKS.map(([a, b]) => {
        const p = at(nodes, a), q = at(nodes, b);
        const inferred = a === "w1" && b === "db" || a === "w2" && b === "db";
        return <line key={a + b} x1={p.x} y1={p.y} x2={q.x} y2={q.y} className={inferred ? "edge inferred" : "edge"} />;
      })}
      {nodes.map((n) => (
        <g key={n.id} className="node" transform={`translate(${n.x} ${n.y})`}>
          <circle r="9" />
          <text y="-16" textAnchor="middle" className="nl">{n.label}</text>
          <text y="24" textAnchor="middle" className="nk">{n.kind}</text>
        </g>
      ))}
    </g>
  );
}

export default function HeroGraphic() {
  return (
    <svg className="hero-graphic" viewBox="0 0 800 410" role="img"
      aria-label="A small AWS setup on the left, with its links, is rebuilt on Leaseweb on the right. Each resource travels along an amber route.">
      <defs>
        <pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="1.5" cy="1.5" r="1.2" className="dot" /></pattern>
        <linearGradient id="fade" x1="0" x2="1"><stop offset="0" stopColor="#E8A800" stopOpacity="0.15" /><stop offset="0.5" stopColor="#E8A800" stopOpacity="0.9" /><stop offset="1" stopColor="#E8A800" stopOpacity="0.15" /></linearGradient>
      </defs>
      <rect width="800" height="410" fill="url(#dots)" />
      <text x="20" y="28" className="side-title">AWS, built by clicking</text>
      <text x="780" y="28" textAnchor="end" className="side-title">Leaseweb, as code</text>
      {AWS.map((a, i) => {
        const b = at(LSW, a.id);
        const mid = (a.x + b.x) / 2;
        const lift = 60 + i * 18;
        const d = `M${a.x + 12} ${a.y} C ${mid - 60} ${a.y - lift}, ${mid + 60} ${b.y - lift}, ${b.x - 12} ${b.y}`;
        return (
          <g key={a.id}>
            <path id={`route-${a.id}`} d={d} className="route-path" stroke="url(#fade)" />
            <circle r="4.5" className="packet">
              <animateMotion dur={`${3.2 + i * 0.45}s`} begin={`${i * 0.35}s`} repeatCount="indefinite" keyPoints="0;1" keyTimes="0;1" calcMode="spline" keySplines="0.45 0 0.25 1">
                <mpath href={`#route-${a.id}`} />
              </animateMotion>
            </circle>
          </g>
        );
      })}
      <Cluster nodes={AWS} side="aws" />
      <Cluster nodes={LSW} side="lsw" />
    </svg>
  );
}
