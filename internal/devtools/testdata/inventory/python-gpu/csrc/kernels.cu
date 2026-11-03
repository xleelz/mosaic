#include <cuda.h>

// __global__ void commented_kernel(int* x) {}

template <typename scalar_t, int BLOCK>
__global__ void __launch_bounds__(256) rms_norm_kernel(scalar_t* out, const scalar_t* in) {
  printf("__global__ void fake_in_string(");
}

__global__ void plain_kernel(int* x) {}

#define DEFINE_KERNEL(name) \
  __global__ void name(int* p) {}
