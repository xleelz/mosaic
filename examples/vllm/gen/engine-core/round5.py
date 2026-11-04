"""Writes build-oracle/round5/engine-core.yaml: the round-5 unit tests as scenarios."""
import os, yaml
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', '..', 'build-oracle', 'round5', 'engine-core.yaml')
W1, W4 = ['full-tp1-llama-8b'], ['full-tp4-llama-70b']


def sc(id, name, steps, expect, fixtures=W1, **kw):
    d = {'id': id, 'name': name, 'fixtures': fixtures}
    d.update(kw)
    d['steps'] = steps
    d['expect'] = expect
    return d


S = []
PROMPT = [1, 2, 3, 4, 5, 6, 7, 8]
for remote in (True, False):
    S.append(sc('oracle5-engine-core-remote-prefill-cached-tokens-' + ('remote' if remote else 'local'),
        'tests/v1/engine/test_output_processor.py:217 test_remote_prefill_cached_tokens_override[%s]' % remote,
        [{'interface': 'output-processor.add-request', 'caller': 'engine-core', 'as': 'add',
          'input': {'request': {'request_id': 'request-0-int', 'external_req_id': 'request-0', 'prompt_token_ids': PROMPT, 'arrival_time': 0,
                                'sampling_params': {'detokenize': False, 'extra_args': {'kv_transfer_params': {'do_remote_prefill': remote, 'remote_prefill_cached_tokens': 5}}}},
                    'has_queue': False}},
         {'interface': 'output-processor.process-outputs', 'caller': 'engine-core', 'as': 'proc',
          'input': {'outputs': [{'request_id': 'request-0-int', 'new_token_ids': [42],
                                 'prefill_stats': {'num_prompt_tokens': 8, 'num_local_cached_tokens': 0, 'num_external_cached_tokens': 7}}]}}],
        ["steps.proc.result.ok && size(steps.proc.result.value.request_outputs) == 1",
         "steps.proc.result.value.request_outputs[0].num_cached_tokens == %d" % (5 if remote else 7)],
        description='P/D disaggregation: with do_remote_prefill the RequestOutput reports the P worker\'s hits (5) from kv_transfer_params; '
                    'otherwise PrefillStats.num_cached_tokens = local + external = 7 (output_processor.py:238-249, 731-742).'))

# Watermark status partitions the finished requests.
def req(rid, sp=None, pooling=None):
    r = {'request_id': rid, 'external_req_id': rid + '-ext', 'prompt_token_ids': [128000, 9906, 1917], 'arrival_time': 0, 'sampling_params': sp}
    if pooling is not None:
        r['pooling_params'] = pooling
    return r


def resolved(wm, skipped, n=1):
    return {'n': n, 'watermarking': wm, '_watermarking_skipped': skipped}


finish = [('wm', 'abort'), ('skip', 'stop'), ('sticky', 'stop'), ('off', 'error'), ('pool', 'stop'), ('0_parent', 'length'), ('1_parent', 'length')]
adds = [('wm', resolved(True, False)), ('skip', resolved(False, True)), ('sticky', resolved(True, True)), ('off', resolved(False, False))]
steps = [{'interface': 'output-processor.add-request', 'caller': 'engine-core', 'as': 'a_' + rid, 'input': {'request': req(rid, sp), 'has_queue': False}} for rid, sp in adds]
steps.append({'interface': 'output-processor.add-request', 'caller': 'engine-core', 'as': 'a_pool', 'input': {'request': req('pool', None, {'task': 'embed'}), 'has_queue': False}})
for idx in range(2):
    steps.append({'interface': 'output-processor.add-request', 'caller': 'engine-core', 'as': 'a_child%d' % idx,
                  'input': {'request': dict(req('%d_parent' % idx, resolved(True, False, n=1)), external_req_id='parent-ext'),
                            'parent_request_id': 'parent', 'index': idx, 'n': 2, 'has_queue': False}})
steps.append({'interface': 'output-processor.process-outputs', 'caller': 'engine-core', 'as': 'proc',
              'input': {'outputs': [{'request_id': rid, 'new_token_ids': [] if rid == 'pool' else [128000], 'finish_reason': fr} for rid, fr in finish]}})
steps.append({'interface': 'stat-logger-manager.record', 'caller': 'engine-core', 'as': 'rec',
              'input': {'scheduler_stats': None, 'iteration_stats': '= steps.proc.result.value.iteration_stats'}})
WMK = lambda st: "state['prometheus-registry'].metrics['vllm:watermark_requests{model_name=\"llama-8b\",engine=\"0\",status=\"%s\"}']" % st
S.append(sc('oracle5-engine-core-watermark-status-partitions-finished',
    'tests/v1/engine/test_output_processor.py:1175 test_watermark_status_partitions_finished_requests',
    steps,
    ["steps.proc.result.ok && steps.rec.result.ok",
     "steps.proc.result.value.iteration_stats.num_watermarked_reqs == 4 && steps.proc.result.value.iteration_stats.num_watermark_skipped_reqs == 1 && steps.proc.result.value.iteration_stats.num_not_watermarked_reqs == 2",
     WMK('watermarked') + " == 4 && " + WMK('skipped') + " == 1 && " + WMK('not_watermarked') + " == 2",
     "sum(state['prometheus-registry'].metrics.filter(k, k.startsWith('vllm:request_success{')).map(k, state['prometheus-registry'].metrics[k])) == 7"],
    config={'watermark-enabled': True},
    description='Seven requests finish (wm, skip, sticky, off, a pooling request, and two n=2 children): watermarked 4 (wm, sticky and both children), skipped 1, not watermarked 2, '
                'which sums to the request_success total (stats.py:636-641, loggers.py:1248-1258).'))

S.append(sc('oracle5-engine-core-cloud-storage-tokenizer-skips-get-model-path',
    'tests/engine/test_arg_utils.py:851 test_cloud_storage_tokenizer_skips_get_model_path',
    [{'interface': 'engine-args.post-init', 'caller': 'python-user', 'as': 'args',
      'input': {'model': 's3://bucket/model', 'tokenizer': 's3://bucket/tokenizer'}}],
    ["steps.args.result.ok && steps.args.result.value.model == 's3://bucket/model' && steps.args.result.value.tokenizer == 's3://bucket/tokenizer'"],
    description='EngineArgs(model=s3://..., tokenizer=s3://...) under HF_HUB_OFFLINE keeps both cloud URIs (arg_utils.py:908-925). '
                'EngineArgs is config-platform\'s; its post-init does not model the HF_HUB_OFFLINE rewrite, so this passes without exercising it (build-oracle/round5/engine-core.md).'))

S.append(sc('oracle5-engine-core-admission-tokens-rejects-when-zero-limit',
    'tests/v1/engine/test_admission_control.py:355 test_admission_tokens_rejects_when_zero_limit',
    [{'interface': 'async-llm.check-admission', 'caller': 'api-server', 'as': 'adm', 'input': {'n': 1}}],
    ["!steps.adm.result.ok && steps.adm.result.error.code == 'max-queued-tokens-error'",
     "steps.adm.result.error.message == 'The engine has reached its prefill token backlog limit. Please try again later or on a different instance.'",
     "calls['stat-logger-manager.record-admission-rejection'] == 0"],
    config={'max-num-queued-tokens': 0, 'disable-log-stats': True},
    description='max_num_queued_tokens=0 with nothing queued: 0 >= 0, so MaxQueuedTokensError. The bare AsyncLLM has no logger manager (disable-log-stats here), so nothing is recorded (async_llm.py:362-379).'))

S.append(sc('oracle5-engine-core-dplb-finished-requests-release-inflight',
    'tests/v1/engine/test_engine_core_client.py:394 test_dplb_finished_requests_release_inflight',
    [{'interface': 'dp-lb-async-mp-client.get-core-engine-for-request', 'caller': 'api-server', 'as': 'pick',
      'input': {'request_id': 'req-1', 'prompt_token_ids': [1, 2, 3], 'sampling_params': {'max_tokens': 1}}},
     {'interface': 'dp-lb-async-mp-client.process-engine-outputs', 'caller': 'api-server', 'as': 'out',
      'input': {'outputs': {'finished_requests': ['req-1']}}}],
    ["steps.pick.result.value.engine == 'dp0'",
     # engine_inflight starts empty, so 0 after one release means the pick counted it as 1
     "steps.out.result.value.released == 1",
     "state['dp-lb-async-mp-client'].engine_inflight.dp0 == 0 && !('req-1' in state['dp-lb-async-mp-client'].reqs_in_flight)"],
    config={'data-parallel-size': 2},
    description='Two engines: the request goes to an engine with in-flight 1; a finished_requests notice for it releases the slot (core_client.py:1642-1697, 1703-1710).'))

for name, target, inst, cfg, fx in [('tp1-load-weights', 'gpu-worker-impl.load-model', 'rank0', {}, W1),
                                    ('tp1-forward', 'gpu-worker-impl.determine-available-memory', 'rank0', {}, W1),
                                    ('tp2-load-weights', 'gpu-worker-impl.load-model', 'rank0', {'tensor-parallel-size': 2}, W4)]:
    S.append(sc('oracle5-engine-core-async-llm-startup-error-' + name,
        'tests/v1/shutdown/test_startup_error.py:48 test_async_llm_startup_error[%s]' % name,
        [{'interface': 'async-llm.from-engine-args', 'caller': 'api-server', 'as': 'e'}],
        ["!steps.e.result.ok && steps.e.result.error.message.matches('initialization fail(ed|ure)')",
         "steps.e.result.error.message == \"Engine core initialization failed. See root cause above. Failed core proc(s): {'EngineCore': 1}\"",
         "!trace.exists(e, e.type == 'call.start' && e.interface == 'scheduler.add-request')",
         "trace.exists(e, e.type == 'call.end' && e.interface == '%s' && has(e.error) && e.error.message == 'Simulated Error in startup!')" % target],
        faults=[{'target': target, 'type': 'error', 'code': 'exception', 'message': 'Simulated Error in startup!', 'instance': inst}],
        config=cfg, max_events=200000,
        description='The model raises during load_weights (or the profiling forward inside determine_available_memory) on one rank: the engine process dies during startup '
                    'and AsyncLLM.from_engine_args raises "Engine core initialization failed. ... Failed core proc(s): {\'EngineCore\': 1}" (utils.py:1431-1440).'))

with open(OUT, 'w') as f:
    f.write('# Round-5 build-oracle scenarios for engine-core. Generated by examples/vllm/gen/engine-core/round5.py.\n')
    yaml.safe_dump({'schema_version': 1, 'id': 'vllm', 'scenarios': S}, f, sort_keys=False, width=200)
print(len(S), 'scenarios ->', os.path.normpath(OUT))
