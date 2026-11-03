declare module 'vscode' {
	export class Disposable {
		dispose(): any;
	}
	export namespace commands {
		export function registerCommand(command: string, callback: (...args: any[]) => any): Disposable;
		export function executeCommand<T = unknown>(command: string, ...rest: any[]): Thenable<T>;
		export function executeCommand<T = unknown>(command: string): Thenable<T>;
		export const onDidExecute: Event<string>;
	}
	namespace comments {
		export function createCommentController(id: string, label: string): CommentController;
	}
}
