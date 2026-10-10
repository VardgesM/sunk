# Independent shared gateway

Copy this directory to `/opt/gateway` once. It is a separate Compose project, not an
application service or release artifact. Application builds/updates never copy it again.
Gateway configuration changes are separate infrastructure changes reviewed by the operator.

See [production migration and rollback](../../docs/gateway.md). In the standalone copy,
keep an independent copy of that runbook with the deployment records.

```bash
cd /opt/gateway
cp gateway.env.example .env
chmod 600 .env
chmod 644 Caddyfile
# Edit .env: preserve current hostname and INSPECTED certificate volume names.
docker compose --env-file .env config --quiet
docker compose --env-file .env build
docker compose --env-file .env run --rm --no-deps caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker compose --env-file .env up -d --wait
```

Only gateway owns host TCP 80/443; container ports 8080/8443 permit UID 1000 without
capabilities. Internal health port 8090 and Caddy admin API are not public (admin is off).
The external network and certificate volumes must already exist. New installations may
create empty volumes; existing installations must reuse inspected volumes.

`GATEWAY_IPV4` must be outside the network's dynamic IP allocation range, and must match
the application trusted proxy IP. Example after checking for subnet conflicts:

```bash
docker network create --subnet 172.30.50.0/24 --ip-range 172.30.50.128/25 web
```

For a future second site, give that project's HTTP service a unique `web` network alias,
keep its database on its own private network, and add a separately reviewed Caddy site:

```caddyfile
shop.example.com {
    reverse_proxy shop-wordpress:80
}
```

This is an example only; it does not install WordPress or enable another domain. Do not
copy Modbus security headers blindly to other applications; their requirements may differ.
Validate, then restart only gateway to apply a Caddyfile change. Gateway restart briefly
affects all hosted sites; application restarts do not restart gateway.
