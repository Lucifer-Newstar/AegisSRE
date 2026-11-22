"""Fixed bounded load program, executed only inside the owned catalog container."""

TRAFFIC_PROGRAM = '''
import concurrent.futures,json,time,urllib.request,urllib.error
seconds=int(input())
assert 1<=seconds<=120
end=time.monotonic()+seconds
def worker(_):
    successes=failures=0
    while time.monotonic()<end:
        try:
            with urllib.request.urlopen("http://127.0.0.1:9001/products",timeout=2) as response:
                response.read(65536)
                successes+=response.status==200
        except (OSError,urllib.error.URLError):
            failures+=1
        time.sleep(0.1)
    return successes,failures
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    counts=list(pool.map(worker,range(8)))
print(json.dumps({"successful_requests":sum(x[0] for x in counts),
                  "failed_requests":sum(x[1] for x in counts),"workers":8}))
'''
