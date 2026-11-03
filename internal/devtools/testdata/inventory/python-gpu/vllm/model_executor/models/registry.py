_TEXT_GENERATION_MODELS = {
    # comment
    "LlamaForCausalLM": ("llama", "LlamaForCausalLM"),
    "MistralForCausalLM": (
        "llama",
        "LlamaForCausalLM",
    ),
}

_VLLM_MODELS = {
    **_TEXT_GENERATION_MODELS,
}

_PREVIOUSLY_SUPPORTED_MODELS = {
    "OldForCausalLM": "0.10.2",
}
