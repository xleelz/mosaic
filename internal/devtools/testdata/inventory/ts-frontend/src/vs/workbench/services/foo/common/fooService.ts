export class FooService implements IFooService {
	declare readonly _serviceBrand: undefined;
}
registerSingleton(IFooService, FooService, InstantiationType.Delayed);
