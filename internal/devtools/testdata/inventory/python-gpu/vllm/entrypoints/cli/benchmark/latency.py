from vllm.entrypoints.cli.benchmark.base import BenchmarkSubcommandBase


class BenchmarkLatencySubcommand(BenchmarkSubcommandBase):
    name = "latency"
    help = "Benchmark latency."
