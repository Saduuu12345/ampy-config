// Package ampyconfig provides a thin Go client for AmpyFin's configuration
// control-plane. It is intentionally minimal for v0: it lets services
// publish/consume config control events over NATS/JetStream and react to
// runtime override files (e.g. runtime/overrides.yaml).
//
// Goals (v0):
//   • Uniform control topics with Python (config_preview/config_apply/…)
//   • Wait-for-applied UX parity (ops CLI + library helper)
//   • Safe-by-default redaction (never log secret values)
//
// Non-goals (v0):
//   • Full schema validation and layering parity (Python is the source of truth)
//   • Built-in secret provider clients (resolve refs in your service or via Python)
//
// Import path:
//   github.com/AmpyFin/ampy-config/go/ampyconfig
//
// CLIs built from this module:
//   • ampyconfig-ops       – publish preview/apply/secret-rotated
//   • ampyconfig-agent     – consume control events and persist overrides
//   • ampyconfig-listener  – example service listener
//
// Example: publish an apply and wait for applied:
//
//   package main
//
//   import (
//     "context"
//     "encoding/json"
//     "fmt"
//     "time"
//
//     "github.com/nats-io/nats.go"
//   )
//
//   func main() {
//     nc, _ := nats.Connect("nats://127.0.0.1:4222")
//     defer nc.Drain()
//
//     applySubj := "ampy.dev.control.v1.config_apply"
//     appliedSubj := "ampy.dev.control.v1.config_applied"
//     changeID := "chg_" + time.Now().UTC().Format("20060102_150405")
//
//     payload := map[string]any{
//       "change_id":       changeID,
//       "canary_percent":  0,
//       "canary_duration": "0s",
//       "overlay": map[string]any{
//         "oms": map[string]any{
//           "risk": map[string]any{"max_order_notional_usd": 123456},
//         },
//       },
//       "producer": "ops-go@example",
//     }
//     b, _ := json.Marshal(payload)
//     _ = nc.Publish(applySubj, b)
//     _ = nc.Flush()
//
//     sub, _ := nc.SubscribeSync(appliedSubj)
//     ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
//     defer cancel()
//
//     msg, err := sub.NextMsgWithContext(ctx)
//     if err != nil {
//       panic(err)
//     }
//     fmt.Println("applied:", string(msg.Data))
//   }
package ampyconfig
