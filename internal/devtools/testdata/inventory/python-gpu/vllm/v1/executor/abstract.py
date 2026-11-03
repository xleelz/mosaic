class Executor:
    def _init_executor(self):
        self.collective_rpc("init_device")
        self.collective_rpc(
            "load_model",
        )

    def collective_rpc(self, method, args=()):
        raise NotImplementedError
