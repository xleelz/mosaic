from base import *
TG='src/vs/workbench/contrib/testing/'; TSI=TG+'common/testServiceImpl.ts'; TCON=TG+'browser/testing.contribution.ts'; TRS=TG+'common/testResultService.ts'; TPS=TG+'common/testProfileService.ts'
config('testing-save-before-test','testing.saveBeforeTest','boolean',True,True,'Save dirty editors before running tests. No product.json override.',[S(TG+'common/configuration.ts',142,146),'product.json'])
comp('testing-contrib','Testing contribution','workbench','Testing workbench contribution module: test services, views, peek, decorations and commands.',[S(TCON,53,61),S(TCON,142,149)])
comp('test-service','TestService','testing-contrib','Runs tests: resolves profiles, creates a live result, asks trust, saves, and dispatches runs to the test controllers (extension hosts).',
  [CL(TSI,'TestService'),S(TG+'common/testService.ts',28),S(TCON,53)],state={'schema':obj({'controllers':ob(),'tests':ob(),'running':ob()}),'initial':{'controllers':{},'tests':{},'running':{}}})
comp('test-result-service','TestResultService','testing-contrib','Live and past test results.',[CL(TRS,'TestResultService'),S(TRS,73),S(TCON,58)],
  state={'schema':obj({'results':arr(),'next_seq':it()}),'initial':{'results':[],'next_seq':1}})
comp('test-profile-service','TestProfileService','testing-contrib','Run/debug/coverage profiles per controller and the default profiles.',[CL(TPS,'TestProfileService'),S(TPS,19),S(TCON,55)],
  state={'schema':obj({'profiles':ob()}),'initial':{'profiles':{}}})
comp('test-coverage-service','TestCoverageService','testing-contrib','Selected coverage and the "filter to test" selection.',[CL(TG+'common/testCoverageService.ts','TestCoverageService'),S(TG+'common/testCoverageService.ts',23),S(TCON,56)],
  state={'schema':obj({'filter_to_test':{'type':['string','null']}}),'initial':{'filter_to_test':None}})
comp('testing-continuous-run-service','TestingContinuousRunService','testing-contrib','Continuous (watch) test runs per test id.',[CL(TG+'common/testingContinuousRunService.ts','TestingContinuousRunService'),S(TG+'common/testingContinuousRunService.ts',22),S(TCON,57)],
  state={'schema':obj({'running':ob()}),'initial':{'running':{}}})
comp('test-explorer-filter-state','TestExplorerFilterState','testing-contrib','Test explorer filter and the test to reveal.',[CL(TG+'common/testExplorerFilterState.ts','TestExplorerFilterState'),S(TG+'common/testExplorerFilterState.ts',76),S(TCON,59)],
  state={'schema':obj({'reveal':{'type':['string','null']}}),'initial':{'reveal':None}})
comp('testing-peek-opener','TestingPeekOpener','testing-contrib','Opens the test failure peek (also a workbench contribution).',[CL(TG+'browser/testingOutputPeek.ts','TestingPeekOpener'),S(TG+'common/testingPeekOpener.ts',55),S(TCON,60),S(TCON,143)],
  state={'schema':obj({'peeked':{'type':['string','null']}}),'initial':{'peeked':None}})
comp('testing-decoration-service','TestingDecorationService','testing-contrib','Gutter decorations for tests in editors.',[CL(TG+'browser/testingDecorations.ts','TestingDecorationService'),S(TG+'common/testingDecorations.ts',104),S(TCON,61)])
comp('testing-commands','Testing commands','testing-contrib','Commands registered in testing.contribution.ts (API and reveal commands).',[S(TCON,151,290)])
comp('testing-configuration-ui','testingConfigurationUi','testing-contrib','Profile pickers (vscode.pickTestProfile, vscode.pickMultipleTestProfiles).',[S(TG+'browser/testingConfigurationUi.ts',101,159)])
stub('ext-host-testing','run-controller-tests','exthost','ExtHostTestingShape.$runControllerTests: run tests in the extension host controller.',kind='rpc',attributes={'shape':'ExtHostTestingShape'},parent='exthost-runtime',
  request=obj({'run_id':st('run-1'),'controller_id':st('vitest'),'profile_id':it(1),'test_ids':arr(st('vitest/src/util.test.ts'))}),response=obj({'error':{'type':['string','null'],'default':None}}))
stub('ext-host-testing','start-continuous-run','exthost','ExtHostTestingShape.$startContinuousRun.',kind='rpc',attributes={'shape':'ExtHostTestingShape'},
  request=obj({'controller_id':st('vitest'),'profile_id':it(1),'test_ids':arr(st())}),response=obj({'error':{'type':['string','null'],'default':None}}))

iface('test-service','register-test-controller','A controller registered (from MainThreadTesting.$registerTestController).',[M(TSI,'registerTestController')],
  request=obj({'controller_id':st('vitest'),'label':st('Vitest'),'tests':arr(st('vitest/src/util.test.ts'))}),response=ob(),
  behavior=[{'set':{'state.controllers':"= merge(state.controllers, {input.controller_id: {'label': input.label}})"}},
            {'foreach':"= input.tests",'as':'t','steps':[{'set':{'state.tests':"= merge(state.tests, {vars.t: {'controller_id': input.controller_id}})"}}]}])
iface('test-profile-service','add-profile','Add a run profile for a controller.',[M(TPS,'addProfile')],request=obj({'controller_id':st('vitest'),'profile_id':it(1),'group':st('run'),'is_default':bo(True)}),response=ob(),
  behavior=[{'set':{'state.profiles':"= merge(state.profiles, {input.controller_id + '/' + string(input.profile_id): {'controller_id': input.controller_id, 'profile_id': input.profile_id, 'group': input.group, 'is_default': input.is_default}})"}}])
iface('test-profile-service','get-default-profile-for-test','The default profile of the group for a test\'s controller.',[M(TPS,'getDefaultProfileForTest',300)],request=obj({'controller_id':st('vitest'),'group':st('run')}),response=obj({'profile':{'type':['object','null']}}),
  behavior=[{'set':{'vars.p':"= state.profiles.filter(k, state.profiles[k].controller_id == input.controller_id && state.profiles[k].group == input.group).map(k, state.profiles[k])"}},
            {'return':{'profile':"= size(vars.p.filter(p, p.is_default)) > 0 ? vars.p.filter(p, p.is_default)[0] : (size(vars.p) > 0 ? vars.p[0] : null)"}}])
iface('test-service','run-tests','Group requested tests by their default profile, then run the resolved request.',[M(TSI,'runTests')],
  request=obj({'group':st('run'),'test_ids':arr(st('vitest/src/util.test.ts')),'preserve_focus':bo(False)}),response=obj({'result_id':st()}),
  behavior=[{'set':{'vars.known':"= input.test_ids.filter(t, t in state.tests)"}},
            {'if':"size(vars.known) == 0",'then':[{'call':'test-service.run-resolved-tests','input':{'targets':[],'group':"= input.group",'preserve_focus':"= input.preserve_focus"},'as':'r0'},{'return':{'result_id':"= vars.r0.value.result_id"}}]},
            {'call':'test-profile-service.get-default-profile-for-test','input':{'controller_id':"= state.tests[vars.known[0]].controller_id",'group':"= input.group"},'as':'prof'},
            {'set':{'vars.targets':"= vars.prof.value.profile == null ? [] : [{'controller_id': vars.prof.value.profile.controller_id, 'profile_id': vars.prof.value.profile.profile_id, 'test_ids': vars.known}]"}},
            {'call':'test-service.run-resolved-tests','input':{'targets':"= vars.targets",'group':"= input.group",'preserve_focus':"= input.preserve_focus"},'as':'r'},{'return':{'result_id':"= vars.r.value.result_id"}}])
iface('test-service','run-resolved-tests','Create the live result, ask workspace trust, save before test, run each controller\'s targets in parallel, mark the result complete.',[M(TSI,'runResolvedTests'),M(TSI,'saveAllBeforeTest')],
  request=obj({'targets':arr(),'group':st('run'),'preserve_focus':bo(False)}),response=obj({'result_id':st(),'errors':arr()}),
  behavior=[{'call':'test-result-service.create-live-result','input':{'group':"= input.group"},'as':'res'},
            {'call':'workspace-trust-request-service.request-workspace-trust','input':{'message':'Running tests may execute code in your workspace.'},'as':'trust'},
            {'choice':'trust','default':"= vars.trust.value.trusted == true ? 'trusted' : 'denied'",'options':{'trusted':[],'denied':[
               {'call':'test-result-service.mark-complete','input':{'result_id':"= vars.res.value.result_id"}},{'return':{'result_id':"= vars.res.value.result_id",'errors':[]}}]}},
            {'set':{'state.running':"= merge(state.running, {vars.res.value.result_id: true})"}},
            {'if':"!input.preserve_focus && config['testing-save-before-test']",'then':[{'title':'saveAllBeforeTest','source':M(TSI,'saveAllBeforeTest'),'call':'editor-service.save-all','input':{'reason':'explicit'}}]},
            {'parallel':"= input.targets.filter(t, t.controller_id in state.controllers)",'as':'t','join':{'need':'all'},'as_result':'runs','steps':[
               {'title':'getTestController(id)?.runTests: unknown controllers are skipped','source':S(TSI,270,285),'call':'ext-host-testing.run-controller-tests','on':'eh1',
                'input':{'run_id':"= vars.res.value.result_id",'controller_id':"= vars.t.controller_id",'profile_id':"= vars.t.profile_id",'test_ids':"= vars.t.test_ids"},'as':'rr'},{'return':"= vars.rr.value"}]},
            {'set':{'vars.errors':"= vars.runs.results.filter(r, r.ok && has(r.value.error) && r.value.error != null).map(r, r.value.error)"}},
            {'when':"size(vars.errors) > 0",'set':{'ctx.test_run_error':"= 'An error occurred attempting to run tests: ' + vars.errors.join(' ')"}},
            {'set':{'state.running':"= omit(state.running, vars.res.value.result_id)"}},
            {'call':'test-result-service.mark-complete','input':{'result_id':"= vars.res.value.result_id"}},
            {'return':{'result_id':"= vars.res.value.result_id",'errors':"= vars.errors"}}])
iface('test-service','cancel-test-run','Cancel a run (or all runs) and tell the extension hosts.',[M(TSI,'cancelTestRun')],request=obj({'result_id':{'type':['string','null'],'default':None}}),response=ob(),
  behavior=[{'set':{'state.running':"= input.result_id == null ? {} : omit(state.running, input.result_id)",'ctx.test_run_cancelled':True}}])
iface('test-service','get-tests-in-file','Tests known for a file (vscode.testing.getTestsInFile).',[M(TG+'common/mainThreadTestCollection.ts','getNodeByUrl')],request=obj({'uri':st('file:///work/app/src/util.test.ts')}),response=obj({'test_ids':arr(st())}),
  behavior=[{'return':{'test_ids':"= state.tests.map(k, k).filter(k, k.contains(input.uri.split('/work/app/')[1]))"}}])
iface('test-result-service','create-live-result','Create a live result at the head of the results list.',[M(TRS,'createLiveResult',130)],request=obj({'group':st('run')}),response=obj({'result_id':st()}),
  behavior=[{'set':{'vars.id':"= 'run-' + string(state.next_seq)"}},{'set':{'state.results':"= [{'id': vars.id, 'completed': false, 'group': input.group}] + state.results",'state.next_seq':"= state.next_seq + 1"}},{'return':{'result_id':"= vars.id"}}])
iface('test-result-service','mark-complete','Mark a live result complete.',[M(TG+'common/testResult.ts','markComplete')],request=obj({'result_id':st('run-1')}),response=ob(),
  behavior=[{'set':{'state.results':"= state.results.map(r, r.id == input.result_id ? merge(r, {'completed': true, 'completed_at': now}) : r)"}}])
iface('test-result-service','get-results','Past and live results, newest first.',[S(TRS,86,88)],response=obj({'results':arr()}),behavior=[{'return':{'results':"= state.results"}}])
iface('test-result-service','clear','Clear completed results.',[M(TRS,'clear',200)],response=ob(),behavior=[{'set':{'state.results':"= state.results.filter(r, !r.completed)"}}])
iface('testing-continuous-run-service','start','Start a continuous run for a test (and its profiles).',[M(TG+'common/testingContinuousRunService.ts','start',150)],request=obj({'test_id':st('vitest/src/util.test.ts'),'controller_id':st('vitest'),'profile_id':it(1)}),response=ob(),
  behavior=[{'set':{'state.running':"= merge(state.running, {input.test_id: true})"}},
            {'call':'ext-host-testing.start-continuous-run','on':'eh1','input':{'controller_id':"= input.controller_id",'profile_id':"= input.profile_id",'test_ids':["= input.test_id"]}}])
iface('testing-continuous-run-service','stop','Stop a continuous run (all when no test id).',[M(TG+'common/testingContinuousRunService.ts','stop',250)],request=obj({'test_id':{'type':['string','null'],'default':None}}),response=ob(),
  behavior=[{'set':{'state.running':"= input.test_id == null ? {} : omit(state.running, input.test_id)"}}])
iface('testing-continuous-run-service','is-running','Whether a test has a continuous run.',[M(TG+'common/testingContinuousRunService.ts','isSpecificallyEnabledFor') if find(TG+'common/testingContinuousRunService.ts',r'isSpecificallyEnabledFor\(') else S(TG+'common/testingContinuousRunService.ts',159)],request=obj({'test_id':st('vitest/src/util.test.ts')}),response=obj({'running':bo()}),
  behavior=[{'return':{'running':"= input.test_id in state.running"}}])
iface('test-explorer-filter-state','set-reveal','Set the test the explorer should reveal.',[S(TG+'common/testExplorerFilterState.ts',104)],request=obj({'test_id':st('vitest/src/util.test.ts')}),response=ob(),behavior=[{'set':{'state.reveal':"= input.test_id"}}])
iface('test-coverage-service','set-filter-to-test','Filter coverage to one test (or clear).',[S(TG+'common/testCoverageService.ts',60)],request=obj({'test_id':{'type':['string','null'],'default':None}}),response=ob(),behavior=[{'set':{'state.filter_to_test':"= input.test_id"}}])
iface('testing-peek-opener','open-current-in-editor','Open the current peek message in an editor.',[M(TG+'browser/testingOutputPeek.ts','openCurrentInEditor')],response=ob(),behavior=[{'call':'editor-service.open-editor','input':{'resource':'vscode-test-data://result/message'}}])
iface('testing-peek-opener','try-peek-first-error','Peek the first failure of a test in a result.',[M(TG+'browser/testingOutputPeek.ts','tryPeekFirstError')],request=obj({'test_id':st('vitest/src/util.test.ts')}),response=ob(),behavior=[{'set':{'state.peeked':"= input.test_id"}}])
iface('testing-decoration-service','sync-decorations','Recompute test gutter decorations for an editor.',[CL(TG+'browser/testingDecorations.ts','TestingDecorationService')],response=ob(),behavior=[{'title':'Decorations follow the test collection and results','source':CL(TG+'browser/testingDecorations.ts','TestingDecorationService')}])
