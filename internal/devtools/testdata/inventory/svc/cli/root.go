package cli

import "github.com/spf13/cobra"

var deployCmd = &cobra.Command{Use: "deploy <name>", Short: "Deploy"}
