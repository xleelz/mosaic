export interface MainThreadFooShape extends IDisposable {
	$registerFoo(handle: number): void;
	$unregisterFoo(handle: number): void;
	$queryFoo<T>(q: string): Promise<T>;
}
export interface ExtHostFooShape2 {
	$acceptFoo(dto: IFooDto): void;
}
export interface IFooDto {
	$notRpc(): void;
}
export const MainContext = {
	MainThreadFoo: createProxyIdentifier<MainThreadFooShape>('MainThreadFoo'),
};
