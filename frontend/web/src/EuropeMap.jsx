import { useMemo } from "react";
import { geoMercator, geoPath } from "d3-geo";
import { feature } from "topojson-client";
import world from "world-atlas/countries-110m.json";

// natural earth 1:110m via world-atlas (public domain data, ISC package)
const W = 760, H = 560;
// aws regions outside the eu, and the eu leaseweb data centers they move to
// label offset per city [dx, dy, anchor]
const AWS = [["N. Virginia", -77.5, 39.0, [-10, 18, "end"]], ["Ohio", -83.0, 40.0, [-10, -8, "end"]], ["Montreal", -73.6, 45.5, [10, -6, "start"]]];
const LSW = [["Amsterdam", 4.9, 52.37, [-12, -8, "end"]], ["Frankfurt", 8.68, 50.11, [12, 14, "start"]]];
const ROUTES = [[[-77.5, 39.0], [4.9, 52.37], 3.6], [[-83.0, 40.0], [8.68, 50.11], 4.4]];

export default function EuropeMap() {
  const { countries, project } = useMemo(() => {
    const land = feature(world, world.objects.countries);
    const frame = { type: "Feature", geometry: { type: "MultiPoint", coordinates: [[-92, 28], [24, 62]] } };
    const projection = geoMercator().fitExtent([[10, 10], [W - 10, H - 10]], frame).clipExtent([[0, 0], [W, H]]);
    const path = geoPath(projection);
    return { countries: land.features.map((f) => ({ id: f.id, d: path(f) })).filter((c) => c.d), project: projection };
  }, []);

  const routes = ROUTES.map(([from, to, dur]) => {
    const [sx, sy] = project(from), [ax, ay] = project(to);
    return { d: `M${sx} ${sy} Q ${(sx + ax) / 2} ${Math.min(sy, ay) - 150}, ${ax} ${ay}`, dur };
  });

  return (
    <figure className="europe-fig">
      <EuropeSvg countries={countries} project={project} routes={routes} />
      <figcaption className="eu-legend"><span className="k-aws" />AWS region<span className="k-lsw" />Leaseweb data center</figcaption>
    </figure>
  );
}

function EuropeSvg({ countries, project, routes }) {
  return (
    <svg className="europe" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Map of the North Atlantic. Workloads move from AWS regions in North America to Leaseweb data centers in Amsterdam and Frankfurt.">
      <g className="countries">{countries.map((c) => <path key={c.id} d={c.d} />)}</g>
      {routes.map((r, i) => (
        <g key={i}>
          <path d={r.d} className={i ? "eu-route faint" : "eu-route"} />
          <circle r="5" className="eu-packet"><animateMotion dur={`${r.dur}s`} repeatCount="indefinite" path={r.d} /></circle>
        </g>
      ))}
      {AWS.map(([name, lon, lat, [dx, dy, anchor]]) => {
        const [x, y] = project([lon, lat]);
        return <g key={name} className="city aws" transform={`translate(${x} ${y})`}><circle r="5" /><text x={dx} y={dy} textAnchor={anchor}>{name}</text></g>;
      })}
      {LSW.map(([name, lon, lat, [dx, dy, anchor]]) => {
        const [x, y] = project([lon, lat]);
        return <g key={name} className="city lsw" transform={`translate(${x} ${y})`}><circle r="7" /><circle r="14" className="halo" /><text x={dx} y={dy} textAnchor={anchor}>{name}</text></g>;
      })}
    </svg>
  );
}
