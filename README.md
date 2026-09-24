# RoutePulse

Flask, PostgreSQL/PostGIS, Redis, and Leaflet prototype for GPS trip ingestion, spatial search, trip analytics, and live position updates. The original relational CRUD dashboard and SQL demonstrations remain in the repository.

## Architecture

| Component | Purpose |
| --- | --- |
| Flask + Gunicorn | Trip CRUD, GPS ingestion, spatial search, metrics, WebSocket endpoint |
| PostgreSQL + PostGIS | Trip data, generated `geography(Point,4326)` columns, GiST radius search |
| Redis | Cache-aside trip detail reads, TTL and mutation invalidation, pub/sub between app replicas |
| Leaflet | Map route, stops, geofences, POIs, incoming position markers |
| Prometheus | HTTP duration/request counters, cache hit/miss/error counts, published positions |

`POST /api/trips/{id}/points` commits a position, updates cheap summary counters, invalidates the cached trip, and publishes to `routepulse:trip:{id}:positions`. Every WebSocket subscriber receives the message, including subscribers connected to other app workers. Completing a trip recomputes stops, geofence crossings, and summary data.

## Local setup

Requires Docker with Compose. On a new checkout:

```bash
docker compose up --build -d
docker compose ps
curl http://127.0.0.1:5000/api/health/ready
curl 'http://127.0.0.1:5000/api/nearby/points?lat=45.553&lon=-94.154&radius_m=500'
```

Open <http://127.0.0.1:5000>. Compose initializes a **fresh** PostgreSQL volume with `schema.sql`, `functions.sql`, `views.sql`, and `sample_data.sql`. `schema.sql` drops tables and must never be run against a database whose data you need to retain. To upgrade the original database, back it up and run `migrations/001_postgis.sql` instead. For an empty local reset, `docker compose down -v` permanently deletes the local database volume.

To start Prometheus as well:

```bash
docker compose --profile observability up --build -d
curl http://127.0.0.1:5000/metrics
```

Prometheus is at <http://127.0.0.1:9090>. Local Compose uses a sample password for local development only. For nonlocal use, supply secrets from your environment or a secret manager. The working `.env` file has been removed from this copy; `.env.example` documents the variables.

## API and WebSocket

```bash
curl 'http://127.0.0.1:5000/api/trips'
curl 'http://127.0.0.1:5000/api/trips/1'
curl 'http://127.0.0.1:5000/api/nearby/points?lat=45.553&lon=-94.154&radius_m=500&limit=20'
curl 'http://127.0.0.1:5000/api/health/live'
curl 'http://127.0.0.1:5000/api/health/ready'
```

The spatial endpoint validates coordinates/radius, calls `ST_DWithin(location, ...)` to use the GiST index, then orders matches by `ST_Distance`. GPS writes to active trips use ISO 8601 timestamps with time zones and strictly increasing times. WebSocket subscriptions use `ws://127.0.0.1:5000/ws/trips/{trip_id}` and receive `subscribed`, `position`, `completed`, and `heartbeat` messages. Subscribe and then fetch the trip snapshot to avoid missing changes while connecting; messages are transient and Redis pub/sub does not provide durable replay.

## Verification and performance evidence

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python scripts/smoke.py --base-url http://127.0.0.1:5000
```

Run the smoke test only on a disposable database: it creates and then deletes a trip. With Compose running, benchmark a temporary spatial table and a hot cached route:

```bash
export DB_HOST=localhost DB_PORT=5432 DB_NAME=routepulse DB_USER=routeuser DB_PASS=local-only-password
.venv/bin/python bench/geo_explain.py --rows 1000000 --repeats 5 --output geo-results.json
.venv/bin/python bench/load_http.py --url http://127.0.0.1:5000/api/trips/1 --requests 10000 --concurrency 64 --output load-results.json
```

`geo_explain.py` verifies equal result counts and uses `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` for a calculated-distance predicate versus indexed `ST_DWithin`; it alternates query order and reports medians and actual plan nodes. `load_http.py` records achieved throughput, latency percentiles, and errors on the machine you run it on. For cache hit rate, compare `routepulse_cache_access_total{result="hit"}` and `{result="miss"}` from `/metrics` over the same interval. Record hardware, dataset distribution, concurrency, number of workers/pods, and cache state with results. Neither script establishes any specific performance number until it has been run under the stated conditions.

For a paired cache comparison, set `CACHE_ENABLED=0 docker compose up -d --force-recreate app`, run the HTTP load script after warming the DB, then set `CACHE_ENABLED=1 docker compose up -d --force-recreate app`, warm the trip cache, and repeat with the same concurrency and data. Compare p95 values; the Redis WebSocket transport remains enabled in both runs. The container runs one threaded worker per pod so `/metrics` includes all requests handled by that pod.

## Cloud infrastructure

`infra/terraform/` declares an AWS VPC with public/private subnets, NAT, managed EKS node group, private RDS PostgreSQL, and private Redis ElastiCache. RDS supports PostGIS, but Terraform provisioning alone does **not** enable the extension inside the database. Run the SQL initialization or migration from a trusted host with VPC access before deploying the API. Terraform is not applied by this repository; EKS, NAT, RDS, and ElastiCache incur charges if you apply it.

```bash
cd infra/terraform
terraform init
terraform validate
terraform plan
```

Supply `TF_VAR_db_password` and `TF_VAR_redis_auth_token` through a secret manager or protected environment. Use a protected remote Terraform state backend before real deployment; state can include database and Redis credentials. Do not commit `terraform.tfvars` or state files. After provisioning, build/push the image, replace the image placeholder in `k8s/deployment.yaml`, create the `routepulse-secrets` Kubernetes Secret with `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASS`, and TLS `REDIS_URL`, and apply the manifest. Database initialization requires a VPC-connected environment. The `Service` has type `LoadBalancer`, so exposure and WebSocket support need review for the target network. The Kubernetes CPU/memory values are initial requests and limits, **not measured right-sizing results**.

## Claim status

This is an implementation and measurement harness. It has not been provisioned in AWS or load tested at one million rows in this environment. Do not present ~90% spatial improvement, 90%+ cache hits, ~75% p95 improvement, 500–1,000+ RPS, 0.09% errors, or 30–50% request tuning as observed results until saved evidence supports each number. The demo API has no authentication or tenant separation and should not be exposed publicly without adding those controls.
