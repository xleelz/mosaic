class CLISubcommand:
    """Base class for CLI subcommands."""

    name: str

    def subparser_init(self, subparsers):
        raise NotImplementedError
