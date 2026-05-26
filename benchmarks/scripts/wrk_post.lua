-- wrk lua script: POST JSON payload for inference benchmark

wrk.method = "POST"
wrk.body   = '{"input": "hello"}'
wrk.headers["Content-Type"] = "application/json"

-- Optional: track per-request latency for custom stats
-- wrk does not expose per-request timing by default; we rely on wrk's built-in stats.

function setup(thread)
    -- thread setup if needed
end

function init(args)
    -- per-thread init if needed
end

function request()
    return wrk.format(nil, nil, nil, wrk.body)
end

function response(status, headers, body)
    -- optional: track non-200 responses
end

function done(summary, latency, requests)
    -- Print machine-readable summary lines that our Python parser can pick up
    io.write("\n---BENCH_SUMMARY---\n")
    io.write(string.format("duration_sec=%.3f\n", summary.duration / 1000000))
    io.write(string.format("requests_total=%d\n", summary.requests))
    io.write(string.format("bytes_total=%d\n", summary.bytes))
    io.write(string.format("errors_connect=%d\n", summary.errors.connect))
    io.write(string.format("errors_read=%d\n", summary.errors.read))
    io.write(string.format("errors_write=%d\n", summary.errors.write))
    io.write(string.format("errors_status=%d\n", summary.errors.status))
    io.write(string.format("errors_timeout=%d\n", summary.errors.timeout))
    io.write(string.format("latency_mean_ms=%.3f\n", latency.mean / 1000))
    io.write(string.format("latency_stdev_ms=%.3f\n", latency.stdev / 1000))
    io.write(string.format("latency_max_ms=%.3f\n", latency.max / 1000))
    io.write(string.format("latency_p50_ms=%.3f\n", latency:percentile(50) / 1000))
    io.write(string.format("latency_p90_ms=%.3f\n", latency:percentile(90) / 1000))
    io.write(string.format("latency_p99_ms=%.3f\n", latency:percentile(99) / 1000))
    io.write(string.format("latency_p99.9_ms=%.3f\n", latency:percentile(99.9) / 1000))
    io.write(string.format("rps=%.2f\n", (summary.requests / (summary.duration / 1000000))))
    io.write("---END_SUMMARY---\n")
end
