class EngineCoreClient:
    def add_lora(self, lora_request):
        return self.call_utility("add_lora", lora_request)

    def call_utility(self, method, *args):
        pass
