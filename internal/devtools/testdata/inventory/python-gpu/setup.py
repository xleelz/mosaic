from setuptools import setup

setup(
    name="vllm",
    entry_points={
        "console_scripts": ["vllm = vllm.entrypoints.cli.main:main"],
        "vllm.general_plugins": ["lora_resolver = vllm.plugins.lora:register"],
    },
)
