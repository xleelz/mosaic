export function registerAction2(ctor: { new(): Action2 }): IDisposable {
	return CommandsRegistry.registerCommand({ id: descriptor.id, handler: run });
}
