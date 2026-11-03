import threading


class EngineCore:
    def step(self):
        return self.scheduler.schedule()

    def add_lora(self, lora_request):
        return True

    def abort_requests(self, request_ids):
        pass


class EngineCoreProc(EngineCore):
    def __init__(self):
        self.input_thread = threading.Thread(target=self.process_input_sockets, daemon=True)

    def run_busy_loop(self):
        while self._handle_shutdown():
            self._process_engine_step()

    def process_input_sockets(self):
        with self.make_sockets() as sockets:
            while True:
                self.input_queue.put(sockets.recv())

    def _drain(self, sockets):
        for s in sockets:
            while True:
                if not s.poll():
                    break
