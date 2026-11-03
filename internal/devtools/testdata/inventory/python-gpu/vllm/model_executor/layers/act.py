import triton
import triton.language as tl
from numba import jit

from vllm.utils.torch_utils import direct_register_custom_op


def _silu_impl(x):
    return x


direct_register_custom_op(
    op_name="silu_fused",
    op_func=_silu_impl,
    mutates_args=[],
)


@triton.jit
def _silu_kernel(x_ptr, n, BLOCK: tl.constexpr):
    pass


@triton.autotune(configs=[], key=["n"])
@triton.jit(do_not_specialize=["n"])
def _tuned_kernel(x_ptr, n):
    pass


@jit(nopython=True)
def not_triton(x):
    return x
