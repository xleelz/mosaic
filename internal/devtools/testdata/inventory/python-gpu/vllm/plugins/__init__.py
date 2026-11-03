PLATFORM_PLUGINS_GROUP = "vllm.platform_plugins"


def load_plugins_by_group(group):
    from importlib.metadata import entry_points

    return entry_points(group=group)
