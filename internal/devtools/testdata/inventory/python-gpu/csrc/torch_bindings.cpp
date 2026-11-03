#include "core/registration.h"

STABLE_TORCH_LIBRARY_FRAGMENT(_C, ops) {
  // ops.def("commented(Tensor x) -> ()");
  ops.def("rms_norm(Tensor! out, Tensor input, Tensor weight, float eps) -> ()");
  ops.def(
      "fused(Tensor a, "
      "Tensor b) -> Tensor");
}

STABLE_TORCH_LIBRARY_IMPL(_C, CUDA, ops) {
  ops.impl("rms_norm", TORCH_BOX(&rms_norm));
}
