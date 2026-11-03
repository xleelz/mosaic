from vllm.entrypoints.cli.types import CLISubcommand


class ServeSubcommand(CLISubcommand):
    """The `serve` subcommand."""

    name = "serve"

    def subparser_init(self, subparsers):
        return subparsers.add_parser(self.name)
