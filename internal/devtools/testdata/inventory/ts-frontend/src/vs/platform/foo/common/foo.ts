export const IFooService = createDecorator<IFooService>('fooService');
export interface IFooService {
	readonly _serviceBrand: undefined;
}
export function createDecorator<T>(serviceId: string): ServiceIdentifier<T> {
	return undefined!;
}
