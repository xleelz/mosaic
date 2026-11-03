@extHostNamedCustomer(MainContext.MainThreadFoo)
export class MainThreadFoo extends Disposable implements MainThreadFooShape {
	$registerFoo(handle: number): void { }
	$unregisterFoo(handle: number): void { }
	$queryFoo<T>(q: string): Promise<T> { return undefined!; }
}
