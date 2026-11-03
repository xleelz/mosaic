from abc import abstractmethod


class PoolingMixin:
    def encode(self, prompts):
        return []

    @abstractmethod
    def must_override(self):
        raise NotImplementedError
