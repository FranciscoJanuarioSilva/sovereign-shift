# Regions and locations

## Leaseweb public cloud region codes (provider `region` values)
Leaseweb reuses AWS-style codes, but they don't mean the same city as on AWS. The biggest trap: AWS `eu-west-3` is Paris, Leaseweb `eu-west-3` is Amsterdam. Never copy the AWS region string across.

| Leaseweb code | City | Confidence |
|---|---|---|
| `eu-west-3` | Amsterdam (AMS-01/02) | confirmed: developer API regions sample + KB AZ names |
| `eu-central-1` | Frankfurt | confirmed: developer API regions sample |
| `eu-west-2` | London | inferred, verify |
| `us-east-1` | Washington DC area (WDC) | inferred, verify |
| `us-west-1` | San Francisco | inferred, verify |
| `ca-central-1` | Montreal | inferred, verify |
| `ap-southeast-1` | Singapore | inferred, verify |
| `ap-northeast-1` | Tokyo | inferred, verify |

Verify all of them with `GET https://api.leaseweb.com/publicCloud/v1/regions` (header `X-LSW-Auth: <token>`) once we have a token, then write the result to `mappings/regions.yaml`.

## AWS region -> recommended Leaseweb location
Sovereignty first (EU entity and EU data center), then latency.

| AWS region | Leaseweb | Why |
|---|---|---|
| eu-west-1 Dublin | `eu-west-3` Amsterdam | closest EU, flagship location, new platform lives here |
| eu-west-2 London | `eu-west-3` Amsterdam (or `eu-west-2` London if they must stay in the UK) | UK is not EU, default to Amsterdam and say why |
| eu-west-3 Paris | `eu-west-3` Amsterdam or `eu-central-1` Frankfurt | no Paris DC |
| eu-central-1 Frankfurt | `eu-central-1` Frankfurt | same city |
| eu-central-2 Zurich | `eu-central-1` Frankfurt | |
| eu-north-1 Stockholm | `eu-west-3` Amsterdam | |
| eu-south-1/2 Milan, Spain | `eu-central-1` Frankfurt | |
| us-* | `us-east-1` / `us-west-1`, with a note that EU locations are the sovereign option | US entity, not EU-sovereign |
| ca-central-1 | `ca-central-1` Montreal | |
| ap-southeast-1 Singapore | `ap-southeast-1` | |
| ap-northeast-1 Tokyo | `ap-northeast-1` | |
| others | nearest of the above, `--target-region` overrides | |

Object storage endpoints: NL `nl.object-storage.io`, DE `de.object-storage.io`, UK, US, CA, SG (see `leaseweb-platform.md`). Pick the one in the same country as the compute region.

Dedicated server DCs (for big workloads): AMS-01, AMS-02, FRA-10, LON-01, LON-11, WDC-02, NYC-01, SFO-12, MTL-02, SIN-01, SYD-10, HKG-10 and more US sites.
