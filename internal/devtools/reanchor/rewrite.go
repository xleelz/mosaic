package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"

	"go.yaml.in/yaml/v3"

	"github.com/xleelz/mosaic/internal/model"
)

// Keys whose values are data (inputs, schemas, attributes), never citations.
var dataKeys = map[string]bool{"input": true, "return": true, "fail": true, "set": true, "wait": true,
	"attributes": true, "request": true, "response": true, "schema": true, "state": true, "initial": true,
	"choices": true, "expect": true, "store": true, "faults": true, "errors": true}

// found is one citation found in a document and its fate.
type found struct {
	Where string // "file:line" (YAML) or a JSON path
	anchored
}

// rewriter maps the citations of one document.
type rewriter struct {
	ch       changes
	from, to string // full shas
	found    []found
	problems []string // citations that could not be rewritten
	edits    int      // citation strings or fields changed
}

// pinnedElsewhere reports whether an object citation's sha names a commit
// other than from. An empty sha is unpinned.
func (r *rewriter) pinnedElsewhere(sha string) bool {
	return sha != "" && !strings.HasPrefix(r.from, strings.ToLower(sha))
}

// newSHA is the target sha in the length of the sha it replaces.
func (r *rewriter) newSHA(old string) string {
	if len(old) >= len(r.to) || len(old) < 4 {
		return r.to
	}
	return r.to[:len(old)]
}

// ---- YAML: rewrite citation scalars in place, keeping everything else ----

type yamlEdit struct {
	line, col int // 1-based, col in characters, of the first character of the value
	old, new  string
}

func (r *rewriter) yaml(name string, data []byte) ([]byte, error) {
	var root yaml.Node
	if err := yaml.Unmarshal(data, &root); err != nil {
		return nil, err
	}
	var edits []yamlEdit
	scalar := func(n *yaml.Node, newVal string) {
		if n.Value == newVal {
			return
		}
		col := n.Column
		switch n.Style {
		case yaml.DoubleQuotedStyle, yaml.SingleQuotedStyle:
			col++
		case 0, yaml.TaggedStyle, yaml.FlowStyle:
		default:
			r.problems = append(r.problems, fmt.Sprintf("%s:%d: block scalar citation %q not rewritten", name, n.Line, n.Value))
			return
		}
		edits = append(edits, yamlEdit{n.Line, col, n.Value, newVal})
	}
	var citation func(n *yaml.Node)
	citation = func(n *yaml.Node) {
		where := fmt.Sprintf("%s:%d", name, n.Line)
		switch n.Kind {
		case yaml.ScalarNode:
			scalar(n, r.ch.rewriteText(n.Value, func(a anchored) { r.found = append(r.found, found{where, a}) }))
		case yaml.MappingNode:
			fields := map[string]*yaml.Node{}
			for i := 0; i+1 < len(n.Content); i += 2 {
				fields[n.Content[i].Value] = n.Content[i+1]
			}
			sha := fields["sha"]
			if sha != nil && r.pinnedElsewhere(sha.Value) {
				if fields["path"] != nil {
					src := model.Source{Path: fields["path"].Value}
					src.Line, _ = strconv.Atoi(valueOf(fields["line"]))
					src.EndLine, _ = strconv.Atoi(valueOf(fields["end_line"]))
					r.found = append(r.found, found{where, anchored{Old: src, New: src, Statuses: []string{stPinned}}})
				}
				return
			}
			if sha != nil {
				scalar(sha, r.newSHA(sha.Value))
			}
			p := fields["path"]
			if p == nil || p.Kind != yaml.ScalarNode {
				return // the document's own source: {repo, sha}
			}
			src := model.Source{Path: p.Value}
			src.Line, _ = strconv.Atoi(valueOf(fields["line"]))
			src.EndLine, _ = strconv.Atoi(valueOf(fields["end_line"]))
			a := r.ch.reanchor(src)
			r.found = append(r.found, found{where, a})
			scalar(p, a.New.Path)
			if l := fields["line"]; l != nil && a.New.Line > 0 {
				scalar(l, strconv.Itoa(a.New.Line))
			}
			if e := fields["end_line"]; e != nil && src.EndLine > 0 {
				scalar(e, strconv.Itoa(max(a.New.EndLine, a.New.Line)))
			}
		}
	}
	var walk func(n *yaml.Node)
	walk = func(n *yaml.Node) {
		switch n.Kind {
		case yaml.DocumentNode, yaml.SequenceNode:
			for _, c := range n.Content {
				walk(c)
			}
		case yaml.MappingNode:
			for i := 0; i+1 < len(n.Content); i += 2 {
				k, v := n.Content[i].Value, n.Content[i+1]
				switch {
				case k == "sources" && v.Kind == yaml.SequenceNode:
					for _, c := range v.Content {
						citation(c)
					}
				case k == "source":
					citation(v)
				case !dataKeys[k]:
					walk(v)
				}
			}
		case yaml.AliasNode:
			// Aliases repeat an anchored node that is rewritten where it is defined.
		}
	}
	walk(&root)
	return r.apply(name, data, edits), nil
}

func valueOf(n *yaml.Node) string {
	if n == nil {
		return ""
	}
	return n.Value
}

// apply makes the edits, right to left within each line, checking that each
// replaced span holds the old value.
func (r *rewriter) apply(name string, data []byte, edits []yamlEdit) []byte {
	if len(edits) == 0 {
		return data
	}
	lines := bytes.SplitAfter(data, []byte("\n"))
	sort.SliceStable(edits, func(a, b int) bool {
		if edits[a].line != edits[b].line {
			return edits[a].line < edits[b].line
		}
		return edits[a].col > edits[b].col
	})
	for _, e := range edits {
		if e.line < 1 || e.line > len(lines) {
			r.problems = append(r.problems, fmt.Sprintf("%s:%d: citation %q not found", name, e.line, e.old))
			continue
		}
		ln := lines[e.line-1]
		off := byteOffset(ln, e.col-1)
		if off < 0 || !bytes.HasPrefix(ln[off:], []byte(e.old)) {
			// yaml columns are characters; fall back to bytes before giving up.
			if off = e.col - 1; off < 0 || off > len(ln) || !bytes.HasPrefix(ln[off:], []byte(e.old)) {
				r.problems = append(r.problems, fmt.Sprintf("%s:%d: citation %q is escaped or spans lines; not rewritten", name, e.line, e.old))
				continue
			}
		}
		var b []byte
		b = append(b, ln[:off]...)
		b = append(b, e.new...)
		b = append(b, ln[off+len(e.old):]...)
		lines[e.line-1] = b
		r.edits++
	}
	return bytes.Join(lines, nil)
}

// byteOffset is the byte offset of character n in line, or -1.
func byteOffset(line []byte, n int) int {
	off := 0
	for i := 0; i < n; i++ {
		if off >= len(line) {
			return -1
		}
		_, size := utf8.DecodeRune(line[off:])
		off += size
	}
	return off
}

// ---- JSON: rewrite the structure, keeping key order and number text ----

// object is a JSON object with its key order.
type object struct {
	keys []string
	vals map[string]any
}

func (r *rewriter) json(data []byte) ([]byte, error) {
	dec := json.NewDecoder(bytes.NewReader(data))
	dec.UseNumber()
	v, err := decodeOrdered(dec)
	if err != nil {
		return nil, err
	}
	if _, err := dec.Token(); err != io.EOF {
		return nil, fmt.Errorf("unexpected data after the JSON value")
	}
	v = r.walkJSON("$", v)
	var b bytes.Buffer
	encodeOrdered(&b, v, "")
	b.WriteByte('\n')
	return b.Bytes(), nil
}

func (r *rewriter) walkJSON(path string, v any) any {
	switch t := v.(type) {
	case *object:
		for _, k := range t.keys {
			p := path + "." + k
			switch {
			case k == "sources":
				if l, ok := t.vals[k].([]any); ok {
					for i := range l {
						l[i] = r.citationJSON(fmt.Sprintf("%s[%d]", p, i), l[i])
					}
				}
			case k == "source":
				t.vals[k] = r.citationJSON(p, t.vals[k])
			case !dataKeys[k]:
				t.vals[k] = r.walkJSON(p, t.vals[k])
			}
		}
	case []any:
		for i := range t {
			t[i] = r.walkJSON(fmt.Sprintf("%s[%d]", path, i), t[i])
		}
	}
	return v
}

func (r *rewriter) citationJSON(where string, v any) any {
	note := func(a anchored) { r.found = append(r.found, found{where, a}) }
	switch t := v.(type) {
	case string:
		n := r.ch.rewriteText(t, note)
		if n != t {
			r.edits++
		}
		return n
	case *object:
		num := func(k string) int {
			n, _ := strconv.Atoi(fmt.Sprint(t.vals[k]))
			return n
		}
		path, _ := t.vals["path"].(string)
		sha, _ := t.vals["sha"].(string)
		if r.pinnedElsewhere(sha) {
			if path != "" {
				src := model.Source{Path: path, Line: num("line"), EndLine: num("end_line")}
				note(anchored{Old: src, New: src, Statuses: []string{stPinned}})
			}
			return v
		}
		if sha != "" && r.newSHA(sha) != sha {
			t.vals["sha"] = r.newSHA(sha)
			r.edits++
		}
		if path == "" {
			return v
		}
		src := model.Source{Path: path, Line: num("line"), EndLine: num("end_line")}
		a := r.ch.reanchor(src)
		note(a)
		if a.New == src {
			return v
		}
		r.edits++
		t.vals["path"] = a.New.Path
		if _, ok := t.vals["line"]; ok && a.New.Line > 0 {
			t.vals["line"] = json.Number(strconv.Itoa(a.New.Line))
		}
		if _, ok := t.vals["end_line"]; ok && src.EndLine > 0 {
			t.vals["end_line"] = json.Number(strconv.Itoa(max(a.New.EndLine, a.New.Line)))
		}
	}
	return v
}

func decodeOrdered(dec *json.Decoder) (any, error) {
	tok, err := dec.Token()
	if err != nil {
		return nil, err
	}
	switch d := tok.(type) {
	case json.Delim:
		switch d {
		case '{':
			o := &object{vals: map[string]any{}}
			for dec.More() {
				kt, err := dec.Token()
				if err != nil {
					return nil, err
				}
				k := kt.(string)
				v, err := decodeOrdered(dec)
				if err != nil {
					return nil, err
				}
				if _, dup := o.vals[k]; !dup {
					o.keys = append(o.keys, k)
				}
				o.vals[k] = v
			}
			_, err := dec.Token()
			return o, err
		case '[':
			l := []any{}
			for dec.More() {
				v, err := decodeOrdered(dec)
				if err != nil {
					return nil, err
				}
				l = append(l, v)
			}
			_, err := dec.Token()
			return l, err
		}
	}
	return tok, nil
}

// encodeOrdered writes v as json.MarshalIndent(v, "", "  ") would.
func encodeOrdered(b *bytes.Buffer, v any, indent string) {
	switch t := v.(type) {
	case *object:
		if len(t.keys) == 0 {
			b.WriteString("{}")
			return
		}
		b.WriteString("{\n")
		for i, k := range t.keys {
			kb, _ := json.Marshal(k)
			b.WriteString(indent + "  ")
			b.Write(kb)
			b.WriteString(": ")
			encodeOrdered(b, t.vals[k], indent+"  ")
			if i < len(t.keys)-1 {
				b.WriteByte(',')
			}
			b.WriteByte('\n')
		}
		b.WriteString(indent + "}")
	case []any:
		if len(t) == 0 {
			b.WriteString("[]")
			return
		}
		b.WriteString("[\n")
		for i, x := range t {
			b.WriteString(indent + "  ")
			encodeOrdered(b, x, indent+"  ")
			if i < len(t)-1 {
				b.WriteByte(',')
			}
			b.WriteByte('\n')
		}
		b.WriteString(indent + "]")
	case json.Number:
		b.WriteString(string(t))
	default:
		x, _ := json.Marshal(t)
		b.Write(x)
	}
}
