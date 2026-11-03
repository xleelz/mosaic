from vllm.entrypoints.pooling import PoolingMixin


class LLM(
    PoolingMixin,
):
    """An LLM.

    Spans lines, and a docstring line at column 0 must not end the class:
like this one.
    """

    def __init__(self, model: str) -> None:
        self.model = model

    def generate(self, prompts):
        """Generate."""
        return self.llm_engine.collective_rpc("get_model_inspection")

    @property
    def tokenizer(self):
        return None

    def chat(self, messages):
        return []

    def _private(self):
        pass
