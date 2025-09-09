// Package ampyconfig provides a thin Go client for AmpyFin's typed configuration,
// secret resolution, and control-plane reload events.
//
// It mirrors the Python ampy-config features:
//   - Layered effective config (defaults → env profile → overlays → ENV → runtime overrides)
//   - Secret references (e.g., secret://..., aws-sm://...) with TTL caching (provider stubs ok)
//   - Subscriptions to control topics over NATS JetStream:
//       ampy.<env>.control.v1.{config_preview,config_apply,config_applied,secret_rotated}
//
// See subpackages for details:
//
//   - ampyconfig/config   : effective config loading & merging helpers
//   - ampyconfig/secrets  : secret reference types + resolver interfaces
//   - ampyconfig/bus      : NATS/JetStream control-plane helpers
//
// Example:
//
//   import (
//     "context"
//     "github.com/AmpyFin/ampy-config/go/ampyconfig/pkg/config"
//   )
//
//   func main() {
//     ctx := context.Background()
//     eff, prov, err := config.LoadEffective(ctx, config.Options{
//       ProfileYAML: "examples/dev.yaml",
//       DefaultsYAML: "config/defaults.yaml",
//     })
//     _ = eff; _ = prov; _ = err
//   }
//
// For command-line tools, see cmd/ampyconfig-ops, cmd/ampyconfig-agent, cmd/ampyconfig-listener.
package ampyconfig
