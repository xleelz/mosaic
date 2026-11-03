package main

import (
	"fmt"
	"slices"
	"testing"
)

func funcFixture(t *testing.T) string {
	return writeTree(t, map[string]string{
		"go.mod": "module example.com/app\n",
		"svc/a.go": `
package svc

type Server struct{}

func New() *Server { return &Server{} }

func (s *Server) Handle() {
	s.helper()
}

func (s *Server) helper() {}

func generic[T any](x T) T { return x }

func (b *Box[T]) Get() T { var z T; return z }
`,
		"svc/a_test.go": `
package svc

import "testing"

func TestHandle(t *testing.T) {}
`,
		"other/b.go": `
package other

func Elsewhere() {}
`,
		"py/mod.py": `
import functools

def top(a):
    def inner():
        pass
    return inner

@functools.cache
def _private():
    return 1

class Engine:
    def __init__(self):
        pass

    async def step(self):
        pass

    def _drain(self):
        pass

    class Inner:
        def go(self):
            pass
`,
		"py/test_mod.py": `
def test_top():
    pass
`,
		"web/lib.ts": `
export function exported(a: number): { x: number } {
  return { x: a };
}

function local() {
  return 1;
}

export const arrow = async (x: string): Promise<void> => {
  await x;
};

const short = (x: number) => x + 1

export default function () {}

export function overload(a: string): void;
export function overload(a: any) {}

describe("x", function () {});

export class Svc<T> extends Base<{ a: 1 }> {
  private readonly n = 1;
  constructor(private x: number) { super(); }
  async run(): Promise<void> {}
  private hidden() {}
  #secret() {}
  static make() { return new Svc(); }
  handler = (e: Event) => { this.run(); }
  abstract todo(): void;
  get size() { return 1 }
}

class Local {
  go() {}
}
`,
		"web/lib.test.ts": `
export function helper() {}
`,
	})
}

func funcSummary(es []Entry) []string {
	var out []string
	for _, e := range es {
		if !slices.Contains(OptKinds, e.Kind) {
			continue
		}
		s := fmt.Sprintf("%s %s:%d-%d %s exported=%v", e.Kind, e.File, e.Line, e.EndLine, e.Name, e.Exported != nil && *e.Exported)
		if e.Test {
			s += " test"
		}
		out = append(out, s)
	}
	return out
}

func TestFuncKinds(t *testing.T) {
	root := funcFixture(t)
	es, err := Scan(root, Options{Kinds: OptKinds})
	if err != nil {
		t.Fatal(err)
	}
	got := funcSummary(es)
	want := []string{
		"go-func other/b.go:3-3 Elsewhere exported=true",
		"go-func svc/a.go:5-5 New exported=true",
		"go-func svc/a.go:7-9 Server.Handle exported=true",
		"go-func svc/a.go:11-11 Server.helper exported=false",
		"go-func svc/a.go:13-13 generic exported=false",
		"go-func svc/a.go:15-15 Box.Get exported=true",
		"py-func py/mod.py:3-6 top exported=true",
		"py-func py/mod.py:8-10 _private exported=false",
		"py-func py/mod.py:13-14 Engine.__init__ exported=true",
		"py-func py/mod.py:16-17 Engine.step exported=true",
		"py-func py/mod.py:19-20 Engine._drain exported=false",
		"py-func py/mod.py:23-24 Engine.Inner.go exported=true",
		"ts-func web/lib.ts:1-3 exported exported=true",
		"ts-func web/lib.ts:5-7 local exported=false",
		"ts-func web/lib.ts:9-11 arrow exported=true",
		"ts-func web/lib.ts:13-13 short exported=false",
		"ts-func web/lib.ts:15-15 default exported=true",
		"ts-func web/lib.ts:18-18 overload exported=true",
		"ts-func web/lib.ts:24-24 Svc.constructor exported=true",
		"ts-func web/lib.ts:25-25 Svc.run exported=true",
		"ts-func web/lib.ts:26-26 Svc.hidden exported=false",
		"ts-func web/lib.ts:27-27 Svc.secret exported=false",
		"ts-func web/lib.ts:28-28 Svc.make exported=true",
		"ts-func web/lib.ts:29-29 Svc.handler exported=true",
		"ts-func web/lib.ts:31-31 Svc.size exported=true",
		"ts-func web/lib.ts:35-35 Local.go exported=false",
	}
	if !slices.Equal(got, want) {
		t.Errorf("got\n%s\nwant\n%s", join(got), join(want))
	}

	// test functions only on request, flagged
	es, _ = Scan(root, Options{Kinds: OptKinds, IncludeTestFuncs: true})
	var tests []string
	for _, s := range funcSummary(es) {
		if len(s) > 5 && s[len(s)-5:] == " test" {
			tests = append(tests, s)
		}
	}
	wantTests := []string{
		"go-func svc/a_test.go:5-5 TestHandle exported=true test",
		"py-func py/test_mod.py:1-2 test_top exported=true test",
		"ts-func web/lib.test.ts:1-1 helper exported=true test",
	}
	if !slices.Equal(tests, wantTests) {
		t.Errorf("tests: got\n%s\nwant\n%s", join(tests), join(wantTests))
	}

	// off by default
	es, _ = Scan(root, Options{})
	if s := funcSummary(es); len(s) != 0 {
		t.Errorf("function kinds without --kinds: %v", s)
	}

	// one kind, restricted to a scope's paths
	es, _ = Scan(root, Options{Kinds: []string{KindGoFunc}, Paths: []string{"./svc/a.go", "web"}})
	got = funcSummary(es)
	if len(got) != 5 || got[0] != "go-func svc/a.go:5-5 New exported=true" {
		t.Errorf("paths: %s", join(got))
	}
	for _, e := range es {
		if !inPaths(e.File, []string{"svc/a.go", "web"}) {
			t.Errorf("entry outside the paths: %+v", e)
		}
	}
}

func join(ss []string) string {
	out := ""
	for _, s := range ss {
		out += "  " + s + "\n"
	}
	return out
}
