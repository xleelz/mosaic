from vllm.entrypoints.cli.types import CLISubcommand


class BenchmarkSubcommandBase(CLISubcommand):
    help: str
