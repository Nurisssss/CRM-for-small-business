"""NFR-01 Concurrency Test: sends 50 simultaneous requests at once and measures response time."""
import concurrent.futures, json, os, tempfile, threading, time, urllib.request
import app

NUM_REQUESTS = 50

def main():
    tmp = tempfile.mkdtemp()
    app.DB_PATH = os.path.join(tmp, "nfr01_load.db")
    app.SESSIONS.clear()
    app.FAILED.clear()
    app.ThreadingHTTPServer.request_queue_size = 128

    srv = app.make_server(0)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    # Authenticate once to obtain a valid session cookie
    login_req = urllib.request.Request(
        base + "/api/login",
        method="POST",
        data=json.dumps({"username": "aruzhan", "password": "cashier123"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(login_req) as r:
        cookie = r.headers["Set-Cookie"].split(";")[0]

    # Barrier ensures all 50 threads launch their HTTP request at the exact same instant
    barrier = threading.Barrier(NUM_REQUESTS)

    def send_one(idx):
        endpoints = [
            "/api/products",
            "/api/rules",
            "/api/customer?phone=%2B7%20700%20000%2001%2001",
            "/api/points-log?customer_id=1",
            "/api/me",
        ]
        path = endpoints[idx % len(endpoints)]
        req = urllib.request.Request(base + path, headers={"Cookie": cookie})
        barrier.wait()
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read()
            dt = (time.perf_counter() - t0) * 1000
            return resp.status, len(body), dt

    start_all = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_REQUESTS) as pool:
        results = list(pool.map(send_one, range(NUM_REQUESTS)))
    total_ms = (time.perf_counter() - start_all) * 1000

    srv.shutdown()

    ok_count = sum(1 for status, _, _ in results if status == 200)
    latencies = [dt for _, _, dt in results]
    print(f"NFR-01 Load Test Results ({NUM_REQUESTS} concurrent requests):")
    print(f"  Succeeded (HTTP 200): {ok_count}/{NUM_REQUESTS}")
    print(f"  Total wall-clock time: {total_ms:.2f} ms ({total_ms / 1000:.3f} s)")
    print(f"  Average latency:       {sum(latencies) / len(latencies):.2f} ms")
    print(f"  Min / Max latency:     {min(latencies):.2f} ms / {max(latencies):.2f} ms")
    assert ok_count == NUM_REQUESTS, f"Expected all {NUM_REQUESTS} requests to return 200, got {ok_count}"

if __name__ == "__main__":
    main()