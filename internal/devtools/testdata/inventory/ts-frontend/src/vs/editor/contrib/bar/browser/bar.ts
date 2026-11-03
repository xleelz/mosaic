class BarAction extends EditorAction {
	constructor() {
		super({
			id: 'editor.action.bar',
			label: nls.localize2('bar', "Bar"),
			precondition: undefined,
		});
	}
}
registerEditorAction(BarAction);
registerEditorCommand(new BarCommand({
	id: 'editor.bar.accept',
	precondition: undefined,
	handler: x => x.accept(),
}));
class BarController implements IEditorContribution {
	static readonly ID = 'editor.contrib.bar';
}
registerEditorContribution(BarController.ID, BarController, EditorContributionInstantiation.Lazy);
