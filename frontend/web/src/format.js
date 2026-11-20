export const money = (value) =>
  Number.isFinite(value) ? new Intl.NumberFormat("en-IE", { style: "currency", currency: "EUR" }).format(value) : "No price";

export const AWS_REGIONS = {
  "eu-north-1": "Stockholm", "eu-west-1": "Ireland", "eu-west-2": "London", "eu-west-3": "Paris",
  "eu-central-1": "Frankfurt", "eu-central-2": "Zurich", "eu-south-1": "Milan", "eu-south-2": "Spain",
  "us-east-1": "N. Virginia", "us-east-2": "Ohio", "us-west-1": "N. California", "us-west-2": "Oregon",
  "ca-central-1": "Canada", "ap-southeast-1": "Singapore", "ap-northeast-1": "Tokyo",
};

// leaseweb reuses aws-style codes for different cities (docs/research/regions-and-locations.md)
export const LEASEWEB_REGIONS = {
  "eu-west-3": "Amsterdam", "eu-central-1": "Frankfurt", "eu-west-2": "London", "us-east-1": "Washington DC",
  "us-west-1": "San Francisco", "ca-central-1": "Montreal", "ap-southeast-1": "Singapore", "ap-northeast-1": "Tokyo",
};

export const STATUS = {
  auto: { label: "Automatic", hint: "Generated and ready to apply" },
  partial: { label: "Partial", hint: "Generated, with a note to check" },
  manual: { label: "Manual", hint: "Needs a person, steps in the runbook" },
  unsupported: { label: "Not supported", hint: "Listed for review" },
};

export const SEVERITY = ["critical", "high", "medium", "low", "info"];

export const cloudName = (cloud) => ({ aws: "AWS", cloudflare: "Cloudflare", leaseweb: "Leaseweb" })[cloud] ?? cloud ?? "Source";
