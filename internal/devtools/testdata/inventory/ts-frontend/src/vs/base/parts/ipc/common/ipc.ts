export interface IChannelServer<TContext = string> {
	registerChannel(channelName: string, channel: IServerChannel<TContext>): void;
}
export class IPCServer {
	registerChannel(channelName: string, channel: IServerChannel): void {
		this.channelServer.registerChannel(channelName, channel);
	}
}
