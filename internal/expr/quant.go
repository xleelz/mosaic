package expr

import (
	"cel.dev/cel-go/cel"
	"cel.dev/cel-go/common"
	"cel.dev/cel-go/common/ast"
	"cel.dev/cel-go/common/operators"
	"cel.dev/cel-go/common/types"
	"cel.dev/cel-go/parser"
)

// Counting quantifiers for invariants (DESIGN §16.2), as macros:
//
//	exactlyOne(list, x, pred)  exactly one element x satisfies pred
//	exactlyOne(list, pred)     the same, with the element named it
//	exactlyOne(list)           exactly one element is true
//	atMostOne(...)             at most one, in the same three forms
//	atLeastOne(...)            at least one, in the same three forms
//
// For example exactlyOne(calls, it.interface == 'lock.acquire' &&
// it.ok) or exactlyOne([steps.a.result.ok, steps.b.result.ok]).
func quantMacros() cel.EnvOption {
	var ms []cel.Macro
	for name, ok := range map[string]func(eh parser.ExprHelper, n ast.Expr) ast.Expr{
		"exactlyOne": func(eh parser.ExprHelper, n ast.Expr) ast.Expr {
			return eh.NewCall(operators.Equals, n, eh.NewLiteral(types.Int(1)))
		},
		"atMostOne": func(eh parser.ExprHelper, n ast.Expr) ast.Expr {
			return eh.NewCall(operators.LessEquals, n, eh.NewLiteral(types.Int(1)))
		},
		"atLeastOne": func(eh parser.ExprHelper, n ast.Expr) ast.Expr {
			return eh.NewCall(operators.GreaterEquals, n, eh.NewLiteral(types.Int(1)))
		},
	} {
		for argc := 1; argc <= 3; argc++ {
			ms = append(ms, cel.GlobalMacro(name, argc, countMacro(argc, ok)))
		}
	}
	return cel.Macros(ms...)
}

// countMacro expands to a comprehension that counts the elements
// satisfying the predicate and hands the count to result.
func countMacro(argc int, result func(parser.ExprHelper, ast.Expr) ast.Expr) cel.MacroFactory {
	return func(eh parser.ExprHelper, _ ast.Expr, args []ast.Expr) (ast.Expr, *common.Error) {
		v, pred := "it", ast.Expr(nil)
		switch argc {
		case 1:
			pred = eh.NewCall(operators.Equals, eh.NewIdent(v), eh.NewLiteral(types.True))
		case 2:
			pred = args[1]
		case 3:
			if args[1].Kind() != ast.IdentKind {
				return nil, eh.NewError(args[1].ID(), "argument must be a simple name")
			}
			v, pred = args[1].AsIdent(), args[2]
		}
		accu := eh.AccuIdentName()
		if v == accu || v == parser.AccumulatorName {
			return nil, eh.NewError(args[0].ID(), "iteration variable overwrites accumulator variable")
		}
		step := eh.NewCall(operators.Conditional, pred,
			eh.NewCall(operators.Add, eh.NewAccuIdent(), eh.NewLiteral(types.Int(1))), eh.NewAccuIdent())
		return eh.NewComprehension(args[0], v, accu, eh.NewLiteral(types.Int(0)), eh.NewLiteral(types.True), step,
			result(eh, eh.NewAccuIdent())), nil
	}
}
