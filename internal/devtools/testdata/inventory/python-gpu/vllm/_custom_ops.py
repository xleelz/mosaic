import torch


def rms_norm(out, input, weight, epsilon):
    torch.ops._C.rms_norm(out, input, weight, epsilon)


def fused(a, b):
    return torch.ops._C.fused(a, b)


def helper():
    return 1


def uses_python_op(x):
    return torch.ops.vllm.silu_fused(x)
