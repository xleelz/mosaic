use clap::{Args, Parser, Subcommand};

#[derive(Parser, Debug)]
pub struct CliCore {
	#[clap(subcommand)]
	pub subcommand: Option<Commands>,
}

#[derive(Subcommand, Debug, Clone)]
pub enum Commands {
	/// Create a tunnel that's accessible from anywhere.
	Tunnel(TunnelArgs),

	/// Manage extensions.
	#[clap(name = "ext")]
	Extension(ExtensionArgs),

	/// Print process usage.
	Status,
}

#[derive(Args, Debug, Clone)]
pub struct TunnelArgs {
	#[clap(subcommand)]
	pub subcommand: Option<TunnelSubcommand>,
}

fn helper<'a>(x: &'a str) -> &'a str { x }

#[derive(Subcommand, Debug, Clone)]
pub enum TunnelSubcommand {
	/// Delete servers.
	Prune,
	/// Rename the machine.
	Rename(TunnelRenameArgs),
}
