"""Round 3: give each scenario the trimming left without a state/trace check a
boundary one. calls['X'] / calls_by_instance['X@i'] become trace counts; some
scenarios get a new boundary expectation; a few keep their original internal one
(restored from the pre-trim copy) where nothing at the boundary shows the effect."""
import re, sys, yaml
P = 'parts/50-scenarios.yaml'
BEFORE = sys.argv[1]
H = sys.argv[2].split(',')
T = "trace.filter(e, e.type == 'call.start' && e.interface == '%s'%s).size()"
def conv(e):
    e = re.sub(r"calls_by_instance\['([^'@]+)@([^']+)'\]", lambda m: T % (m.group(1), " && e.instance == '%s'" % m.group(2)), e)
    return re.sub(r"calls\['([^']+)'\]", lambda m: T % (m.group(1), ''), e)
def ex(i, extra=''): return "trace.exists(e, e.type == 'call.start' && e.interface == '%s'%s)" % (i, extra)
ADD = {
 'engine-core-generate-queued-tokens-full': ["state['prometheus-registry'].metrics['vllm:admission_rejections'] == 1"],
 'engine-core-generate-stop-string': [ex('scheduler.finish-requests')],
 'engine-core-generate-n2-fanout': [T % ('engine-core-proc.process-input-sockets', " && e.input.request_type == 'ADD'") + ' == 2'],
 'engine-core-generate-engine-dies-mid-step': [ex('scheduler.shutdown')],
 'engine-core-generate-fault-tolerant': [ex('scheduler.finish-requests') + ' && !' + ex('scheduler.shutdown')],
 'engine-core-tp4-rank-timeout': [ex('scheduler.shutdown')],
 'engine-core-tp4-worker-dies': [ex('scheduler.shutdown')],
 'engine-core-abort-then-step': [ex('scheduler.finish-requests', " && e.input.request_ids == ['chatcmpl-abc123-00000001']")],
 'engine-core-shutdown-then-health': ["trace.exists(e, e.type == 'kill')"],
 'engine-core-profile-engine-failure-clears-session': [T % ('gpu-worker-impl.profile', '') + ' == 2'],
 'engine-core-encode-unsupported-task': ['!' + ex('engine-core-proc.process-input-sockets', " && e.input.request_type == 'ADD'")],
 'engine-core-encode-supported-task': [ex('engine-core-proc.process-input-sockets', " && e.input.request_type == 'ADD'")],
 'engine-core-startup-load-failure': ['!' + ex('kv-cache-utils.get-kv-cache-configs')],
 'engine-core-llm-engine-add-then-step': [T % ('scheduler.update-from-output', '') + ' == 1'],
 'engine-core-llm-engine-step-engine-dead': ['!' + ex('scheduler.schedule')],
 'engine-core-llm-engine-n2-and-abort': [T % ('engine-core-proc.process-input-sockets', " && e.input.request_type == 'ABORT'") + ' == 1'],
 'engine-core-llm-engine-sleep-wake': [ex('scheduler.reset-prefix-cache')],
 'engine-core-llm-engine-startup': [T % ('block-pool.init', '') + ' == 3'],
 'engine-core-graceful-shutdown-tp4-workers': [ex('scheduler.shutdown')],
}
RESTORE = {  # scenario -> original expectation index
 'engine-core-ft-recovery-timeout': [1], 'engine-core-startup-custom-prometheus-plugin': [0],
 'engine-core-engine-process-dies': [2], 'engine-core-llm-engine-from-engine-args-sync-client': [0],
 'engine-core-api-counters-and-logging': [0], 'engine-core-errored-state': [2],
 'engine-core-parallel-sampling-final-only': [3], 'engine-core-output-kinds': [2],
 'engine-core-graceful-shutdown-drain-teardown': [1],
}
old = {s['id']: s for s in yaml.safe_load(open(BEFORE))['scenarios']}
def q(s): return '"%s"' % s.replace('\\', '\\\\').replace('"', '\\"')
lines = open(P).read().split('\n')
out, cur, i = [], None, 0
while i < len(lines):
    l = lines[i]
    m = re.match(r'  - id: (\S+)', l)
    if m: cur = m.group(1)
    if cur in H and l == '    expect:':
        out.append(l); i += 1
        exps = []
        while i < len(lines) and lines[i].startswith('      - '):
            exps.append(yaml.safe_load(lines[i][8:])); i += 1
        exps = [conv(e) for e in exps]
        # drop exact duplicates the trim left behind
        seen = []
        for e in exps:
            if e not in seen: seen.append(e)
        exps = seen + ADD.get(cur, []) + [old[cur]['expect'][k] for k in RESTORE.get(cur, [])]
        out += ['      - ' + q(e) for e in exps]
        continue
    out.append(l); i += 1
open(P, 'w').write('\n'.join(out))
