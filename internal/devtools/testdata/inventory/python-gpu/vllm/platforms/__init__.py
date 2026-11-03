from vllm.plugins import PLATFORM_PLUGINS_GROUP, load_plugins_by_group


def cuda_platform_plugin():
    return "vllm.platforms.cuda.CudaPlatform"


builtin_platform_plugins = {
    "cuda": cuda_platform_plugin,
}


def resolve():
    return load_plugins_by_group(PLATFORM_PLUGINS_GROUP)
