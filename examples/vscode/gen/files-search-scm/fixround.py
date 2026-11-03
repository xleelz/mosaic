"""Fix round (after judging) for the files-search-scm fragment: shared document text (text in the
editor's text model), save/revert on the active editor, create contents, search streaming with
TextSearchManager/ripgrep and token cancel, workspace symbols, files.eol, features, and the
matching scenario rewrites (fixround_post.py). Called by gen.py before dumping."""
import copy, re
import yaml

HERE = '/home/lbethay/workplace/mosaic/examples/vscode/gen/files-search-scm'


def apply(d):
    def idx(doc):
        return {(i['component'], i['name']): i for i in doc['interfaces']}



    I = idx(d)


    def put_iface(i):
        k = (i['component'], i['name'])
        for n, x in enumerate(d['interfaces']):
            if (x['component'], x['name']) == k:
                d['interfaces'][n] = i
                return
        d['interfaces'].append(i)


    for f in ['fixround_textfiles.yaml', 'fixround_search.yaml', 'fixround_files.yaml']:
        for i in yaml.safe_load(open(f'{HERE}/{f}')):
            put_iface(i)
    I = idx(d)


    # boundary stubs, copied from the owners' fragments when this round was made (frozen so the output is reproducible)
    for i in yaml.safe_load(open(f'{HERE}/fixround_stubs.yaml')):
        put_iface(i)
    I = idx(d)

    # working copy create: forward each file's contents to createFile
    w = I[('working-copy-file-service', 'create')]
    w['request']['properties']['files']['items']['properties']['contents'] = {'type': 'string', 'default': ''}
    w['errors'] = [{'code': 'file-modified-since', 'status': 0, 'retryable': False}]
    for st in w['behavior']:
        if isinstance(st, dict) and st.get('foreach') and st['steps'][0].get('call') == 'file-service.create-file':
            st['steps'][0]['input']['content'] = "= has(vars.f.contents) ? vars.f.contents : ''"
            st['steps'][0]['title'] = 'Create on disk with the operation contents (createFile(resource, contents, {overwrite}))'
            st['steps'][0]['source'] = 'src/vs/workbench/services/workingCopy/common/workingCopyFileService.ts:371-372'

    # move/copy: remember the dirty snapshot from the text model
    wr = I[('text-file-models', 'on-will-run-working-copy-file-operation')]
    for st in wr['behavior']:
        if isinstance(st, dict) and st.get('foreach') == '= input.files':
            st['steps'] = [
                st['steps'][0],
                {'foreach': "= state.models.map(r, r).filter(r, r == vars.f.source || r.startsWith(vars.f.source + '/'))", 'as': 'r',
                 'steps': [
                     {'if': 'state.models[vars.r].dirty', 'then': [
                         {'title': 'A dirty source model contributes its text model snapshot', 'source': 'src/vs/workbench/services/textfile/common/textFileEditorModelManager.ts:247',
                          'call': 'text-model.get-value', 'input': {'uri': '= vars.r'}, 'as': 'snap'}]},
                     {'title': 'Remember source models (and their dirty snapshot) with their target resource',
                      'source': 'src/vs/workbench/services/textfile/common/textFileEditorModelManager.ts:213-249',
                      'set': {'vars.restore': "= vars.restore + [{'source': vars.r, 'target': vars.f.target + vars.r.substring(size(vars.f.source)), 'snapshot': state.models[vars.r].dirty ? vars.snap.value.value : '', 'dirty': state.models[vars.r].dirty}]"}}]}]

    # components
    comps = {c['id']: c for c in d['components']}
    comps['search-model']['state']['initial']['current_token'] = ''
    tsp = comps['text-file-save-participant']['state']
    tsp['initial']['running'] = {}
    tsp['initial']['runs'] = 0
    tsp['schema']['properties']['running'] = {'type': 'object'}
    tsp['schema']['properties']['runs'] = {'type': 'integer'}
    comps['search-model']['state']['schema']['properties']['current_token'] = {'type': 'string'}
    new_comps = [
        {'id': 'text-search-manager', 'name': 'TextSearchManager', 'kind': 'module', 'layer': 'workbench', 'parent': 'search-service',
         'summary': 'TextSearchManager / NativeTextSearchManager: runs a TextSearchProvider for a text query in the extension host (per-folder options, maxResults trimming, limitHit, result collection). Runs in the extension host process; modeled under the search service whose code it is.',
         'sources': ['src/vs/workbench/services/search/common/textSearchManager.ts:34-47', 'src/vs/workbench/services/search/node/textSearchManager.ts:12'],
         'attributes': {'owner': 'files-search-scm'}},
        {'id': 'ripgrep-text-search-engine', 'name': 'RipgrepTextSearchEngine', 'kind': 'module', 'layer': 'workbench', 'parent': 'text-search-manager',
         'summary': 'RipgrepTextSearchEngine behind RipgrepSearchProvider: spawns rg per folder, parses its JSON output into file matches, stops at maxResults (hitLimit kills rg) or on cancellation.',
         'sources': ['src/vs/workbench/services/search/node/ripgrepTextSearchEngine.ts:25-27', 'src/vs/workbench/services/search/node/ripgrepSearchProvider.ts:14-21'],
         'attributes': {'owner': 'files-search-scm'}},
        {'id': 'workspace-symbol-provider-registry', 'name': 'WorkspaceSymbolProviderRegistry', 'kind': 'module', 'layer': 'workbench', 'parent': 'workbench',
         'summary': 'WorkspaceSymbolProviderRegistry: the workspace symbol providers (one proxy per extension provider), queried by getWorkspaceSymbols.',
         'sources': ['src/vs/workbench/contrib/search/common/search.ts:56-83'],
         'attributes': {'owner': 'files-search-scm'},
         'state': {'schema': {'type': 'object', 'properties': {'providers': {'type': 'array'}}}, 'initial': {'providers': []}}},
        {'id': 'text-model', 'kind': 'module', 'parent': 'editor', 'attributes': {'boundary': True, 'owner': 'editor'}},
        {'id': 'ext-host-language-features', 'kind': 'module', 'parent': 'exthost-runtime', 'attributes': {'boundary': True, 'owner': 'exthost'}},
    ]
    for c in new_comps:
        if c['id'] not in comps:
            d['components'].append(c)
    comps = {c['id']: c for c in d['components']}
    tfs = comps.get('text-file-service')

    # schemas
    for s in d['schemas']:
        if s['id'] == 'FilesTextFileModel':
            s['summary'] = ('One text file model as get returns it. The stored entry of text-file-models.models holds only the file state '
                            '(dirty, saved_version_id = the alternative version id remembered at save, mtime, etag, size, encoding, eol and the conflict/error/orphaned/readonly flags); '
                            'value, version_id, alternative_version_id and language_id are read from the editor\'s text model.')
            props = s['schema']['properties']
            props['alternative_version_id'] = {'type': 'integer'}
            props['encoding'] = {'type': 'string', 'examples': ['utf8']}
            props['eol'] = {'type': 'string', 'examples': ['\n']}
        if s['id'] == 'SearchTextQuery':
            s['schema']['properties']['folder_queries'] = {
                'type': 'array', 'description': 'ITextQuery.folderQueries: per-folder options such as fileEncoding',
                'items': {'type': 'object', 'properties': {'folder': {'type': 'string', 'examples': ['file:///work/app']},
                                                           'file_encoding': {'type': 'string', 'examples': ['windows1252']}}}}

    # config files.eol (owner: this area; the editor reads it in ModelService)
    if not any(c['id'] == 'files-eol' for c in d['configs']):
        d['configs'].append({'id': 'files-eol', 'type': 'string', 'value': 'auto', 'default': 'auto',
                             'summary': 'files.eol: \\n | \\r\\n | auto (the OS end of line). No product.json override, so deployed = default. A new text file model records the resolved EOL; the editor\'s ModelService applies it to new text models.',
                             'sources': ['src/vs/workbench/contrib/files/browser/files.contribution.ts:216-230', 'src/vs/editor/common/services/modelService.ts:184-194'],
                             'attributes': {'key': 'files.eol'}})

    # fixture seed: file state only
    seed = d['fixtures'][0]
    m = seed['state']['text-file-models']['models']['file:///work/app/src/main.ts']
    for k in ('value', 'version_id', 'language_id'):
        m.pop(k, None)
    m['encoding'] = 'utf8'
    m['eol'] = '\n'
    seed['summary'] = seed['summary'].replace('a clean src/main.ts text file model', 'the file state of a clean src/main.ts text file model (its text is the editor\'s text model, editor-seed)')

    # flows: features
    FEAT = {'files-save': ['feature:save-and-revert'], 'files-revert': ['feature:save-and-revert'],
            'files-save-model': ['feature:auto-save'], 'files-external-change': ['feature:file-watching'],
            'search-find-in-files': ['feature:search'], 'scm-input-type': ['feature:scm'], 'scm-accept-input': ['feature:scm']}
    for f in d['flows']:
        if f['id'] in FEAT:
            f['tags'] = (f.get('tags') or []) + FEAT[f['id']]

    # scenarios: shared document text
    TEXT_KEYS = ('value', 'version_id', 'language_id')


    def move_text(state):
        out = {}
        for k, v in list(state.items()):
            if not k.startswith('text-file-models'):
                continue
            inst = k[len('text-file-models'):]
            for r, mm in (v.get('models') or {}).items():
                if 'value' in mm:
                    tm = {'value': mm['value'], 'version_id': mm.get('version_id', 1), 'alternative_version_id': mm.get('version_id', 1),
                          'language_id': mm.get('language_id', 'plaintext')}
                    out.setdefault('text-model' + inst, {'models': {}})['models'][r] = tm
                    for kk in TEXT_KEYS:
                        mm.pop(kk, None)
        for k, v in out.items():
            state.setdefault(k, {'models': {}})
            state[k].setdefault('models', {}).update(v['models'])


    for s in d['scenarios']:
        fx = s.get('fixtures') or []
        if 'files-search-scm-seed' in fx and 'editor-seed' not in fx and 'editor-dirty' not in fx:
            s['fixtures'] = fx + (['editor-dirty'] if 'dirty-editor' in fx else ['editor-seed'])
        if s.get('state'):
            move_text(s['state'])
        for st in s.get('steps') or []:
            if isinstance(st, dict) and st.get('state'):
                move_text(st['state'])
        ex = s.get('expect') or []
        s['expect'] = [re.sub(r"state\['text-file-models@w1'\]\.models\['([^']+)'\]\.(value|version_id)",
                              r"state['text-model@w1'].models['\1'].\2", e) for e in ex]


    import sys
    sys.path.insert(0, HERE)
    import fixround_post
    fixround_post.apply(d)
