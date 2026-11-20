"""Read Cloudflare account metadata without fetching Worker code or stored data."""

import os
import re
from collections.abc import Iterator
from datetime import datetime, UTC
from urllib.parse import quote

import httpx


class ScanError(ValueError):
    pass


def scan_account(account: str, client: httpx.Client, *, worker_name: str | None = None) -> dict:
    denied = []
    resources = {}
    base = f"/accounts/{account}"

    def get(path: str, params: dict) -> dict | None:
        response = client.get(path, params=params)
        if response.status_code == 403:
            denied.append(dict(service="cloudflare", region="global", operation=path.replace(account, "<account>"), error="AccessDenied"))
            return None
        if response.status_code != 200:
            raise ScanError(f"Cloudflare scan failed (HTTP {response.status_code})")
        body = response.json()
        if body.get("success") is not True:
            raise ScanError("Cloudflare returned an unsuccessful response")
        return body

    def rows(path: str, params: dict | None = None) -> Iterator[dict]:
        query = dict(params or {})
        seen_cursors: set[str] = set()
        while body := get(path, query):
            result = body["result"]
            yield from result["buckets"] if isinstance(result, dict) else result
            info = body.get("result_info") or {}
            cursor = info.get("cursor") or (info.get("cursors") or {}).get("after")
            if cursor:
                if cursor in seen_cursors:
                    raise ScanError("Cloudflare returned a repeated pagination cursor")
                seen_cursors.add(cursor)
                query["cursor"] = cursor
                continue
            page = query.get("page", 1)
            size = info.get("per_page") or 0
            more = page < (info.get("total_pages") or 1) or 0 < page * size < (info.get("total_count") or 0)
            if not isinstance(result, list) or not result or not more:
                break
            query["page"] = page + 1

    def add(kind: str, key: str, name: str) -> dict:
        ident = f"cf:{kind}:{key}"
        return resources.setdefault(ident, dict(id=ident, type=f"cloudflare_{kind}", name=name,
                                                 region="global", properties={}, relations=[]))

    namespaces = {}
    if worker_name is None:
        for path, kind, key, label in [
            ("storage/kv/namespaces", "kv_namespace", "id", "title"),
            ("d1/database", "d1", "uuid", "name"),
            ("r2/buckets", "r2_bucket", "name", "name"),
            ("workflows", "workflow", "name", "name"),
            ("workers/durable_objects/namespaces", "durable_object_namespace", "id", "name"),
            ("queues", "queue", "queue_name", "queue_name"),
        ]:
            for row in rows(f"{base}/{path}"):
                resource = add(kind, row[key], row[label])
                if kind == "durable_object_namespace":
                    namespaces[row.get("script"), row.get("class")] = row[key]
                if kind == "queue":
                    for consumer in row.get("consumers", []):
                        if script_name := consumer.get("script_name"):
                            resource["relations"].append(dict(type="consumed_by", target=f"cf:worker:{script_name}"))
                if kind == "workflow" and row.get("script_name"):
                    resource["relations"].append(dict(type="runs_on", target="cf:worker:" + row["script_name"]))

    fields = {"r2_bucket": "bucket_name", "d1": "database_id", "kv_namespace": "namespace_id",
              "queue": "queue_name", "service": "service", "workflow": "workflow_name"}
    names = (worker_name,) if worker_name is not None else (script["id"] for script in rows(f"{base}/workers/scripts"))
    for name in names:
        script_path = f"{base}/workers/scripts/{quote(name, safe='')}"
        settings = get(f"{script_path}/settings", {})
        if worker_name is not None and settings is None:
            raise ScanError("The token cannot read the specified Worker’s settings.")
        worker = add("worker", name, name)
        for binding in settings["result"].get("bindings", []) if settings else []:
            kind = binding["type"]
            key = binding.get(fields.get(kind, ""))
            if kind == "durable_object_namespace":
                key = binding.get("namespace_id") or namespaces.get(
                    (binding.get("script_name") or name, binding.get("class_name"))
                )
            if kind == "d1" and not key:
                key = binding.get("id")
            if kind == "r2_bucket" and binding.get("jurisdiction") not in (None, "", "default"):
                kind = "jurisdictional_r2_bucket"
                key = f"{binding['jurisdiction']}:{key}"
            target_kind = "worker" if kind == "service" and (worker_name is None or key == name) else kind
            target = add(target_kind,
                         key or f"{name}/{binding['name']}", key or binding["name"])
            worker["relations"].append(dict(type="binds_" + binding["name"], target=target["id"]))

        schedules = get(f"{script_path}/schedules", {})
        for schedule in schedules["result"]["schedules"] if schedules else []:
            cron = schedule["cron"]
            trigger = add("cron_trigger", f"{name}/{cron}", cron)
            trigger["relations"].append(dict(type="triggers", target=worker["id"]))

    if worker_name is None:
        for zone in rows("/zones", {"account.id": account}):
            domain = zone["name"]
            parent = add("dns_zone", zone["id"], domain)
            for record in rows(f"/zones/{zone['id']}/dns_records"):
                name, kind = record["name"], record["type"]
                resource = add("dns_record", f"{zone['id']}/{name}/{kind}", name)
                resource["relations"] = [dict(type="in_zone", target=parent["id"])]
                props = resource["properties"]
                props.update(domain_name=domain, record_type=kind)
                flattened = kind == "CNAME" and (name == domain or record.get("settings", {}).get("flatten_cname"))
                if record.get("proxied") or flattened or kind not in {"A", "AAAA", "CNAME"}:
                    props["manual_review"] = True
                    props.pop("values", None)
                elif not props.get("manual_review"):
                    ttl = record["ttl"]
                    props["ttl"] = min(props.get("ttl", 2**31), 300 if ttl == 1 else ttl)
                    props.setdefault("values", []).append(record["content"])
    return dict(source="cloudflare", account_id=account, regions=["global"],
                scanned_at=datetime.now(UTC).isoformat(), resources=list(resources.values()), denied=denied)


def scan() -> dict:
    account = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
    token = os.getenv("CLOUDFLARE_API_TOKEN")
    if not re.fullmatch(r"[a-fA-F0-9]{32}", account) or not token:
        raise ScanError("Set CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN for a live scan")
    with httpx.Client(base_url="https://api.cloudflare.com/client/v4", timeout=30,
                      headers={"Authorization": f"Bearer {token}"}) as client:
        try:
            return scan_account(account, client)
        except ScanError:
            raise
        except (httpx.RequestError, KeyError, TypeError, ValueError):
            raise ScanError("Unable to read Cloudflare inventory metadata") from None
