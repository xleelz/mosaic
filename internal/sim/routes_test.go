package sim_test

import (
	"testing"

	"github.com/xleelz/mosaic/internal/sim"
)

// DESIGN §13.1 item 26: request-level addressing, routes and redirects. The
// redirect scenario mirrors a Go test of a debug redirect: the CLI asks for
// /v1/vms/.., the control plane's mux cleans the path and answers 307 to /v1,
// and the client follows the hop.
const routesDoc = `
components:
  - {id: cli}
  - id: control-plane
    router: {hosts: [api.gateway.test], clean_path: 307, not_found: no_such_route}
  - {id: cp-vms, parent: control-plane}
  - {id: cp-root, parent: control-plane}
  - id: gateway
    router: {hosts: ["*.run.gateway.test"], fallback: gateway.proxy}
  - id: auth
    router: {hosts: [auth.gateway.test]}
interfaces:
  - component: cp-root
    name: get-v1
    attributes: {method: GET, path: /v1}
    behavior:
      - {return: {status: 200, body: {service: control-plane}}}
  - component: cp-vms
    name: get-vm
    attributes: {method: GET, path: "/v1/vms/{vmId}"}
    request:
      type: object
      properties: {vm_id: {type: string}, authorization: {type: string}}
    behavior:
      - {return: {status: 200, body: {id: "= input.vm_id", auth: "= has(input.authorization) ? input.authorization : ''", org: "= has(input.x_org_id) ? input.x_org_id : ''", q: "= has(input.query) ? input.query.view : ''"}}}
  - component: cp-vms
    name: get-vm-current
    attributes: {method: GET, path: /v1/vms/current}
    behavior:
      - {return: {status: 200, body: {id: current}}}
  - component: cp-vms
    name: post-vm
    attributes: {method: POST, path: /v1/vms}
    behavior:
      - {return: {status: 201, body: "= input.body"}}
  - component: cp-vms
    name: legacy
    attributes: {method: [POST, PUT], path: /v1/legacy}
    behavior:
      - {return: {status: 303, headers: {Location: /v1/vms/current}}}
  - component: cp-vms
    name: moved
    attributes: {method: ANY, path: "/v1/old/{rest...}"}
    behavior:
      - {return: {status: 308, headers: {location: "= 'http://auth.gateway.test/' + input.rest"}}}
  - component: cp-vms
    name: loop
    attributes: {method: GET, path: /v1/loop}
    behavior:
      - {return: {status: 302, headers: {location: /v1/loop}}}
  - component: auth
    name: whoami
    attributes: {method: ANY, path: /whoami}
    behavior:
      - {return: {status: 200, body: {auth: "= has(input.authorization) ? input.authorization : 'none'", method: "= input.request.method"}}}
  - component: gateway
    name: proxy
    behavior:
      - {return: {status: 200, body: {proxied: "= input.request.path", host: "= input.request.host"}}}
  - component: cli
    name: debug-exchange
    behavior:
      - call: {component: control-plane, method: GET, path: /v1/vms/.., follow_redirects: true}
        targets: [cp-root.get-v1]
        as: r
      - {return: {status: "= vars.r.value.status", final: "= vars.r.route.path", hops: "= vars.r.route.redirects", target: "= vars.r.target"}}
  - component: cli
    name: no-follow
    behavior:
      - call: {host: api.gateway.test, path: /v1/vms/..}
        as: r
      - {return: "= vars.r.value"}
  - component: cli
    name: params
    behavior:
      - call: {host: "api.gateway.test:443", path: "/v1/vms/vm%2D7?view=full", headers: {Authorization: Bearer t, X-Org-Id: o1}}
        as: a
      - call: {component: control-plane, path: /v1/vms/current}
        as: b
      - call: {component: control-plane, method: POST, path: /v1/vms, body: {name: "= 'n' + string(1)"}}
        as: c
      - {return: ["= vars.a.value.body", "= vars.b.value.body", "= vars.c.value", "= vars.a.target", "= vars.a.route.pattern"]}
  - component: cli
    name: misses
    behavior:
      - call: {component: control-plane, path: /v1/nope}
        as: a
        on_error: continue
      - call: {component: control-plane, method: DELETE, path: /v1/vms/x}
        as: b
        on_error: continue
      - call: {host: "= 'edge.run.gateway.test'", path: /v1/models}
        as: c
      - call: {host: nowhere.test, path: /}
        as: d
        on_error: continue
      - {return: ["= vars.a.error", "= vars.b.error", "= vars.c.value.body", "= vars.d.error.code"]}
  - component: cli
    name: methods
    behavior:
      - call: {component: control-plane, method: POST, path: /v1/legacy, body: {x: 1}, follow_redirects: true}
        as: a
      - call: {component: control-plane, method: POST, path: /v1/old/whoami, headers: {authorization: secret}, follow_redirects: true}
        as: b
      - call: {component: control-plane, path: /v1/loop, follow_redirects: true, max_redirects: 3}
        as: c
        on_error: continue
      - {return: ["= vars.a.value.body.id", "= vars.a.route.method", "= vars.b.value.body", "= vars.b.route.component", "= vars.c.error.code", "= size(vars.c.route.redirects)"]}
  - component: cli
    name: by-id
    behavior:
      - {call: cp-vms.get-vm, input: {vm_id: v1}, as: a}
      - {return: "= vars.a.value.body.id"}
flows:
  - {id: debug, entry: {caller: cli, interface: cli.debug-exchange}}
  - {id: no-follow, entry: {caller: cli, interface: cli.no-follow}}
  - {id: params, entry: {caller: cli, interface: cli.params}}
  - {id: misses, entry: {caller: cli, interface: cli.misses}}
  - {id: methods, entry: {caller: cli, interface: cli.methods}}
  - {id: by-id, entry: {caller: cli, interface: cli.by-id}}
scenarios:
  - id: debug-redirect
    flow: debug
    expect:
      - "result.value.status == 200"
      - "result.value.final == '/v1'"
      - "result.value.target == 'cp-root.get-v1'"
      - "result.value.hops == [{'status': 307, 'location': '/v1', 'method': 'GET', 'path': '/v1/vms/..', 'interface': ''}]"
      - "trace.filter(e, e.type == 'route').map(e, e.input.path) == ['/v1/vms/..', '/v1']"
      - "trace.filter(e, e.type == 'route')[0].output.status == 307"
      - "calls['cp-root.get-v1'] == 1"
  - id: no-follow
    flow: no-follow
    expect:
      - "result.value == {'status': 307, 'headers': {'location': '/v1'}}"
  - id: params
    flow: params
    expect:
      - "result.value[0] == {'id': 'vm-7', 'auth': 'Bearer t', 'org': 'o1', 'q': 'full'}"
      - "result.value[1] == {'id': 'current'}"
      - "result.value[2] == {'status': 201, 'body': {'name': 'n1'}}"
      - "result.value[3] == 'cp-vms.get-vm'"
      - "result.value[4] == '/v1/vms/{vmId}'"
  - id: misses
    flow: misses
    expect:
      - "result.value[0].code == 'no_such_route' && result.value[0].status == 404"
      - "result.value[1].code == 'method_not_allowed' && result.value[1].status == 405"
      - "result.value[2] == {'proxied': '/v1/models', 'host': 'edge.run.gateway.test'}"
      - "result.value[3] == 'unknown_host'"
      - "trace.filter(e, e.type == 'route' && e.error != null).size() == 3"
  - id: methods
    flow: methods
    expect:
      - "result.value[0] == 'current'"
      - "result.value[1] == 'GET'"
      - "result.value[2] == {'auth': 'none', 'method': 'POST'}"
      - "result.value[3] == 'auth'"
      - "result.value[4] == 'too_many_redirects'"
      - "result.value[5] == 3"
      - "calls['cp-vms.loop'] == 4"
  - id: by-id
    flow: by-id
    expect:
      - "result.value == 'v1'"
`

func TestRoutes(t *testing.T) {
	doc := langDoc(t, routesDoc)
	for _, sc := range doc.Scenarios {
		t.Run(sc.ID, func(t *testing.T) {
			passes(t, doc, sim.Request{Scenario: sc.ID})
		})
	}
}
