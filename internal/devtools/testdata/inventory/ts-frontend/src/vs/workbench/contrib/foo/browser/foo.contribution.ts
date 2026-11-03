import * as Constants from '../common/fooConstants.js';
import { OPEN_FOO_ID, FOO_PREFIX, NAVIGATE } from '../common/fooConstants.js';

// registerAction2(class Hidden extends Action2 { constructor() { super({ id: 'hidden.comment' }); } });
const note = "registerAction2(class FakeInString extends Action2 {})";

registerAction2(class RefreshFooAction extends Action2 {
	constructor() {
		super({
			id: Constants.FooCommandIds.Refresh,
			title: localize2('refresh', "Refresh"),
			f1: true,
		});
	}
	run(accessor: ServicesAccessor): void { }
});

export class OpenFooAction extends Action2 {
	static readonly ID = OPEN_FOO_ID;
	constructor() {
		super({ id: OpenFooAction.ID, title: 'Open Foo' });
	}
}
registerAction2(OpenFooAction);

abstract class BaseNavAction extends Action2 {
	constructor(opts: IAction2Options, protected dir: number) {
		super(opts);
	}
}
registerAction2(class extends BaseNavAction {
	constructor() {
		super({ id: NAVIGATE.left, title: 'Left' }, 1);
	}
});

abstract class SetModeAction extends Action2 {
	constructor(private readonly setting: string, title: string, id: string) {
		super({ id, title });
	}
}
class TreeModeAction extends SetModeAction {
	static readonly ID = 'foo.treeMode';
	constructor() {
		super(FooSettings.MODE, 'Tree', TreeModeAction.ID);
	}
}
registerAction2(TreeModeAction);

CommandsRegistry.registerCommand(FOO_PREFIX + 'reveal', (accessor, uri) => reveal(uri));
CommandsRegistry.registerCommand({
	id: '_foo.internal',
	handler: async (accessor) => { }
});
KeybindingsRegistry.registerCommandAndKeybindingRule({
	id: Constants.FooCommandIds.Collapse,
	weight: KeybindingWeight.WorkbenchContrib,
	handler: collapseAll,
});

function registerFooCommand(id: string, handler: ICommandHandler) {
	CommandsRegistry.registerCommand(id, handler);
}
OtherRegistry.registerCommand('not.a.vscode.command', () => { });

class FooContribution extends Disposable implements IWorkbenchContribution {
	static readonly ID = 'workbench.contrib.foo';
}
registerWorkbenchContribution2(FooContribution.ID, FooContribution, WorkbenchPhase.AfterRestored);
Registry.as<IWorkbenchContributionsRegistry>(WorkbenchExtensions.Workbench).registerWorkbenchContribution(LegacyFooContribution, LifecyclePhase.Restored);

const fooExtPoint = ExtensionsRegistry.registerExtensionPoint<IFooContribution[]>({
	extensionPoint: 'fooViews',
	jsonSchema: {},
});
