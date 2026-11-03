from vllm.entrypoints.cli.benchmark.base import BenchmarkSubcommandBase
from vllm.entrypoints.cli.types import CLISubcommand


class BenchmarkSubcommand(CLISubcommand):
    name = "bench"

    def subparser_init(self, subparsers):
        bench_parser = subparsers.add_parser(self.name)
        sub = bench_parser.add_subparsers()
        for cmd_cls in BenchmarkSubcommandBase.__subclasses__():
            sub.add_parser(cmd_cls.name)
        return bench_parser
