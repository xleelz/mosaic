package store

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
	"strings"

	"github.com/xleelz/mosaic/internal/model"
)

// Rev is a resolved revision selector: N > 0 is revision N, 0 is the draft.
type Rev struct{ N int }

// Draft is the draft selector.
var Draft = Rev{}

// IsDraft reports whether r is the draft.
func (r Rev) IsDraft() bool { return r.N == 0 }

// String is "draft" or the revision number.
func (r Rev) String() string {
	if r.N == 0 {
		return "draft"
	}
	return strconv.Itoa(r.N)
}

// ResolveRev resolves draft (also ""), latest, N or rN for an existing ontology.
func (s *Store) ResolveRev(ctx context.Context, id, sel string) (Rev, error) {
	if err := s.Exists(ctx, id); err != nil {
		return Rev{}, err
	}
	return s.resolveRev(ctx, id, sel)
}

func (s *Store) resolveRev(ctx context.Context, id, sel string) (Rev, error) {
	sel = strings.TrimSpace(sel)
	if sel == "" || sel == "draft" {
		return Draft, nil
	}
	revs, err := s.revisionNumbers(ctx, id)
	if err != nil {
		return Rev{}, err
	}
	ns := revs[id]
	if sel == "latest" {
		if len(ns) == 0 {
			return Rev{}, errf(CodeNotFound, "ontology %q has no revisions yet", id)
		}
		return Rev{N: ns[len(ns)-1]}, nil
	}
	n, err := strconv.Atoi(strings.TrimPrefix(sel, "r"))
	if err != nil || n < 1 {
		return Rev{}, errf(CodeBadRequest, "invalid revision %q: use draft, latest or a revision number", sel)
	}
	for _, x := range ns {
		if x == n {
			return Rev{N: n}, nil
		}
	}
	return Rev{}, errf(CodeNotFound, "ontology %q has no revision %d", id, n)
}

func asOf(id string, r Rev) string {
	if r.IsDraft() {
		return ""
	}
	return " AS OF '" + tagName(id, r.N) + "'"
}

// canonical re-encodes a stored spec through its typed value, so output
// follows the model's field order whatever order Dolt keeps keys in.
func canonical(kind string, spec []byte) json.RawMessage {
	v, _, err := model.DecodeEntity(kind, spec)
	if err != nil {
		return json.RawMessage(bytes.Clone(spec))
	}
	b, err := json.Marshal(v)
	if err != nil {
		return json.RawMessage(bytes.Clone(spec))
	}
	return b
}

// Entities returns the entities of one kind (all kinds when kind is "") at a
// revision, ordered by kind and id.
func (s *Store) Entities(ctx context.Context, id string, r Rev, kind string) ([]model.Entity, error) {
	q := "SELECT kind, id, spec FROM " + table(id, "entities") + asOf(id, r)
	var args []any
	if kind != "" {
		q += " WHERE kind = ?"
		args = append(args, kind)
	}
	rows, err := s.db.QueryContext(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var out []model.Entity
	for rows.Next() {
		var e model.Entity
		var spec []byte
		if err := rows.Scan(&e.Kind, &e.ID, &spec); err != nil {
			return nil, err
		}
		e.Spec = canonical(e.Kind, spec)
		out = append(out, e)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	sortEntities(out)
	return out, nil
}

func sortEntities(es []model.Entity) {
	order := map[string]int{}
	for i, k := range model.Kinds {
		order[k] = i
	}
	sort.SliceStable(es, func(a, b int) bool {
		if es[a].Kind != es[b].Kind {
			return order[es[a].Kind] < order[es[b].Kind]
		}
		return es[a].ID < es[b].ID
	})
}

// Entity returns one entity's spec at a revision.
func (s *Store) Entity(ctx context.Context, id string, r Rev, kind, eid string) (json.RawMessage, error) {
	var spec []byte
	err := s.db.QueryRowContext(ctx, "SELECT spec FROM "+table(id, "entities")+asOf(id, r)+" WHERE kind = ? AND id = ?", kind, eid).Scan(&spec)
	if isNotFound(err) {
		return nil, errf(CodeNotFound, "%s %q not found at %s", kind, eid, r)
	}
	if err != nil {
		return nil, err
	}
	return canonical(kind, spec), nil
}

// Document assembles the whole ontology at a revision. Name and description
// come from the registry; the document source and its hierarchy fields
// (level, refines, imports) from meta. The issues report
// stored specs that no longer decode.
func (s *Store) Document(ctx context.Context, id string, r Rev) (*model.Document, []model.Issue, error) {
	row, err := s.getRow(ctx, id)
	if err != nil {
		return nil, nil, err
	}
	es, err := s.Entities(ctx, id, r, "")
	if err != nil {
		return nil, nil, err
	}
	doc, issues := model.FromEntities(es)
	doc.ID, doc.Name, doc.Description = row.ID, row.Name, row.Description
	rows, err := s.db.QueryContext(ctx, "SELECT k, v FROM "+table(id, "meta")+asOf(id, r))
	if err != nil {
		return nil, nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var k string
		var v []byte
		if err := rows.Scan(&k, &v); err != nil {
			return nil, nil, err
		}
		applyMeta(doc, k, v)
	}
	if err := rows.Err(); err != nil {
		return nil, nil, err
	}
	return doc, issues, nil
}

// Validate validates the document at a revision, following the imports it
// names in the store (§15.4): an import's issues are reported under its
// alias, and one the store can't resolve is an error.
func (s *Store) Validate(ctx context.Context, id string, r Rev) ([]model.Issue, error) {
	doc, decodeIssues, err := s.Document(ctx, id, r)
	if err != nil {
		return nil, err
	}
	vi, err := s.validateLinked(ctx, doc)
	if err != nil {
		return nil, err
	}
	issues := append(decodeIssues, vi...)
	if issues == nil {
		issues = []model.Issue{}
	}
	return issues, nil
}

// prepared is an entity decoded strictly and re-encoded canonically.
type prepared struct {
	kind, id string
	spec     []byte
}

// prepare strictly decodes a spec of the given kind. With pathID set, a spec
// without an id takes it, and a different id is refused.
func prepare(kind string, raw []byte, pathID string) (prepared, error) {
	raw = bytes.TrimSpace(raw)
	if pathID != "" {
		var m map[string]any
		if err := model.Decode(raw, &m); err != nil || m == nil {
			return prepared{}, errf(CodeBadRequest, "invalid %s: the body must be a JSON object", kind)
		}
		_, hasComp := m["component"]
		_, hasName := m["name"]
		if _, ok := m["id"]; !ok && !(kind == model.KindInterface && (hasComp || hasName)) {
			m["id"] = pathID
			raw, _ = json.Marshal(m)
		}
	}
	v, eid, err := model.DecodeEntity(kind, raw)
	if err != nil {
		return prepared{}, errf(CodeBadRequest, "invalid %s: %v", kind, err)
	}
	if eid == "" {
		return prepared{}, errf(CodeBadRequest, "%s id is required", kind)
	}
	if len(eid) > 160 {
		return prepared{}, errf(CodeBadRequest, "%s id %q is longer than 160 characters", kind, eid)
	}
	if pathID != "" && eid != pathID {
		return prepared{}, errf(CodeBadRequest, "%s id %q does not match %q in the path", kind, eid, pathID)
	}
	b, err := json.Marshal(v)
	if err != nil {
		return prepared{}, errf(CodeBadRequest, "invalid %s: %v", kind, err)
	}
	return prepared{kind: kind, id: eid, spec: b}, nil
}

// draftTx runs fn in one transaction on the ontology's draft, holding the
// ontology's write lock.
func (s *Store) draftTx(ctx context.Context, id string, fn func(*sql.Tx) error) error {
	if err := s.Exists(ctx, id); err != nil {
		return err
	}
	unlock := s.lock(id)
	defer unlock()
	if err := s.Exists(ctx, id); err != nil { // deleted while we waited
		return err
	}
	return s.withConn(ctx, dbName(id), func(c *sql.Conn) error {
		tx, err := c.BeginTx(ctx, nil)
		if err != nil {
			return err
		}
		if err := fn(tx); err != nil {
			_ = tx.Rollback()
			return err
		}
		return tx.Commit()
	})
}

// storedSpec returns the canonical spec of a draft entity, or nil.
func storedSpec(ctx context.Context, tx *sql.Tx, kind, eid string) ([]byte, error) {
	var spec []byte
	err := tx.QueryRowContext(ctx, "SELECT spec FROM entities WHERE kind = ? AND id = ?", kind, eid).Scan(&spec)
	if isNotFound(err) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	return canonical(kind, spec), nil
}

func (s *Store) write(ctx context.Context, tx *sql.Tx, p prepared) error {
	_, err := tx.ExecContext(ctx, "INSERT INTO entities (kind, id, spec, updated_at) VALUES (?, ?, ?, ?) "+
		"ON DUPLICATE KEY UPDATE spec = VALUES(spec), updated_at = VALUES(updated_at)", p.kind, p.id, string(p.spec), s.now())
	return err
}

// Upsert strictly decodes and writes specs of one kind in one transaction.
// With create set, an existing id is a conflict. With pathID set there is one
// spec and its id must match. Unchanged specs are not rewritten, so the
// draft stays clean when nothing changed. It returns the ids written.
func (s *Store) Upsert(ctx context.Context, id, kind string, specs []json.RawMessage, pathID string, create bool) ([]string, error) {
	if len(specs) == 0 {
		return nil, errf(CodeBadRequest, "no %s to write", model.Plural(kind))
	}
	var ps []prepared
	seen := map[string]bool{}
	for i, raw := range specs {
		p, err := prepare(kind, raw, pathID)
		if err != nil {
			if len(specs) > 1 {
				err.(*Error).Message = fmt.Sprintf("items[%d]: %s", i, err.Error())
			}
			return nil, err
		}
		if seen[p.id] {
			return nil, errf(CodeBadRequest, "%s %q appears twice", kind, p.id)
		}
		seen[p.id] = true
		ps = append(ps, p)
	}
	ids := make([]string, 0, len(ps))
	err := s.draftTx(ctx, id, func(tx *sql.Tx) error {
		for _, p := range ps {
			old, err := storedSpec(ctx, tx, kind, p.id)
			if err != nil {
				return err
			}
			if old != nil && create {
				return errf(CodeConflict, "%s %q already exists", kind, p.id)
			}
			if old == nil || !bytes.Equal(old, p.spec) {
				if err := s.write(ctx, tx, p); err != nil {
					return err
				}
			}
			ids = append(ids, p.id)
		}
		return nil
	})
	return ids, err
}

// Patch applies an RFC 7386 JSON merge patch to a draft entity, then decodes
// the result strictly. It returns the new spec.
func (s *Store) Patch(ctx context.Context, id, kind, eid string, patch []byte) (json.RawMessage, error) {
	var pv any
	if err := model.Decode(bytes.TrimSpace(patch), &pv); err != nil {
		return nil, errf(CodeBadRequest, "invalid merge patch: %v", err)
	}
	var out json.RawMessage
	err := s.draftTx(ctx, id, func(tx *sql.Tx) error {
		old, err := storedSpec(ctx, tx, kind, eid)
		if err != nil {
			return err
		}
		if old == nil {
			return errf(CodeNotFound, "%s %q not found in the draft", kind, eid)
		}
		var target any
		if err := model.Decode(old, &target); err != nil {
			return err
		}
		merged, err := json.Marshal(MergePatch(target, pv))
		if err != nil {
			return err
		}
		p, err := prepare(kind, merged, eid)
		if err != nil {
			return err
		}
		out = p.spec
		if bytes.Equal(old, p.spec) {
			return nil
		}
		return s.write(ctx, tx, p)
	})
	return out, err
}

// MergePatch applies an RFC 7386 merge patch to a decoded JSON value.
func MergePatch(target, patch any) any {
	pm, ok := patch.(map[string]any)
	if !ok {
		return patch
	}
	tm, ok := target.(map[string]any)
	if !ok {
		tm = map[string]any{}
	}
	for k, v := range pm {
		if v == nil {
			delete(tm, k)
		} else {
			tm[k] = MergePatch(tm[k], v)
		}
	}
	return tm
}

// DeleteEntity removes an entity from the draft.
func (s *Store) DeleteEntity(ctx context.Context, id, kind, eid string) error {
	return s.draftTx(ctx, id, func(tx *sql.Tx) error {
		res, err := tx.ExecContext(ctx, "DELETE FROM entities WHERE kind = ? AND id = ?", kind, eid)
		if err != nil {
			return err
		}
		if n, _ := res.RowsAffected(); n == 0 {
			return errf(CodeNotFound, "%s %q not found in the draft", kind, eid)
		}
		return nil
	})
}

// PutDocument replaces every draft entity with the document's, atomically,
// and returns the new count per kind. Entities that did not change are left
// alone, so re-importing the same document leaves the draft clean.
func (s *Store) PutDocument(ctx context.Context, id string, doc *model.Document) (map[string]int, error) {
	es, err := doc.Entities()
	if err != nil {
		return nil, errf(CodeBadRequest, "invalid document: %v", err)
	}
	type key struct{ kind, id string }
	want := map[key]prepared{}
	counts := map[string]int{}
	for _, k := range model.Kinds {
		counts[k] = 0
	}
	for _, e := range es {
		p, err := prepare(e.Kind, e.Spec, "")
		if err != nil {
			return nil, err
		}
		k := key{p.kind, p.id}
		if _, dup := want[k]; dup {
			return nil, errf(CodeBadRequest, "duplicate %s id %q", p.kind, p.id)
		}
		want[k] = p
		counts[p.kind]++
	}
	var source []byte
	if doc.Source != nil {
		source, _ = json.Marshal(doc.Source)
	}
	err = s.draftTx(ctx, id, func(tx *sql.Tx) error {
		rows, err := tx.QueryContext(ctx, "SELECT kind, id, spec FROM entities")
		if err != nil {
			return err
		}
		have := map[key][]byte{}
		for rows.Next() {
			var k key
			var spec []byte
			if err := rows.Scan(&k.kind, &k.id, &spec); err != nil {
				rows.Close()
				return err
			}
			have[k] = canonical(k.kind, spec)
		}
		rows.Close()
		if err := rows.Err(); err != nil {
			return err
		}
		for k := range have {
			if _, keep := want[k]; !keep {
				if _, err := tx.ExecContext(ctx, "DELETE FROM entities WHERE kind = ? AND id = ?", k.kind, k.id); err != nil {
					return err
				}
			}
		}
		for k, p := range want {
			if old, ok := have[k]; ok && bytes.Equal(old, p.spec) {
				continue
			}
			if err := s.write(ctx, tx, p); err != nil {
				return err
			}
		}
		if err := setMeta(ctx, tx, "source", source); err != nil {
			return err
		}
		hm := hierarchyMeta(doc)
		for _, k := range hierarchyKeys {
			if err := setMeta(ctx, tx, k, hm[k]); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	return counts, nil
}

// setMeta writes a meta value, or deletes it when v is nil; unchanged
// values are not rewritten.
func setMeta(ctx context.Context, tx *sql.Tx, k string, v []byte) error {
	var old []byte
	err := tx.QueryRowContext(ctx, "SELECT v FROM meta WHERE k = ?", k).Scan(&old)
	if isNotFound(err) {
		old = nil
	} else if err != nil {
		return err
	}
	switch {
	case v == nil && old == nil:
		return nil
	case v == nil:
		_, err = tx.ExecContext(ctx, "DELETE FROM meta WHERE k = ?", k)
		return err
	case old != nil && jsonEqual(old, v):
		return nil
	}
	_, err = tx.ExecContext(ctx, "INSERT INTO meta (k, v) VALUES (?, ?) ON DUPLICATE KEY UPDATE v = VALUES(v)", k, string(v))
	return err
}

func jsonEqual(a, b []byte) bool {
	var x, y any
	if json.Unmarshal(a, &x) != nil || json.Unmarshal(b, &y) != nil {
		return false
	}
	xa, _ := json.Marshal(x)
	ya, _ := json.Marshal(y)
	return bytes.Equal(xa, ya)
}
