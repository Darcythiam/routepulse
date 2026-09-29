# Resource sizing evidence

The manifest contains starter resource requests. To support a later claim about reducing them without an SLO regression:

1. Apply a baseline manifest to a test cluster, then run the same load profile and seeded data for each candidate configuration.
2. Capture `kubectl top pods -l app=routepulse` during steady load and record CPU/memory peak and typical utilization. Also record node size, pod replicas, request/limit values, and load generator location.
3. Save HTTP generator JSON reports and Prometheus query results for both configurations. Example p95 query by pod:

   ```promql
   histogram_quantile(0.95, sum by (le, pod) (rate(routepulse_http_request_duration_seconds_bucket[5m])))
   ```

   Error-rate query:

   ```promql
   sum(rate(routepulse_http_requests_total{status=~"5.."}[5m])) / sum(rate(routepulse_http_requests_total[5m]))
   ```

4. Compute `(baseline_request - new_request) / baseline_request * 100` separately for CPU and memory. Keep a dated report with raw measurements. Do not call the initial values tuned or claim no SLO regression without both runs.
