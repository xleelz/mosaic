const service = new FooService();
const server = new ChildProcessServer();
server.registerChannel('foo', ProxyChannel.fromService(service, disposables));
server?.registerChannel(FooChannelName, new FooChannel(service));
