class AsyncLLM:
    async def generate(self, prompt, sampling_params, request_id):
        yield None

    async def abort(self, request_id) -> None:
        await self.engine_core.call_utility_async("abort_requests", [request_id])
