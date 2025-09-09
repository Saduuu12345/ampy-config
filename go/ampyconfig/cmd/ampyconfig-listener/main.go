package main

import (
	"encoding/json"
	"fmt"
	"os"
	"time"

	"github.com/AmpyFin/ampy-config/go/ampyconfig"
	"github.com/nats-io/nats.go"
)

func main() {
	natsURL := os.Getenv("NATS_URL")
	if natsURL == "" {
		natsURL = "nats://127.0.0.1:4222"
	}
	topic := "ampy/dev"
	effective := "runtime/overrides.yaml" // the file your Python agent writes

	client := ampyconfig.New(natsURL, topic, effective)
	if err := client.Connect(); err != nil { panic(err) }
	defer client.Close()

	ld := ampyconfig.NewLoader(effective)
	cfg, _ := ld.Load()
	v, _ := ampyconfig.GetInt(cfg, "oms", "risk", "max_order_notional_usd")
	fmt.Printf("[go-service] initial max_order_notional_usd=%d\n", v)

	subs := client.Subjects()

	_, err := client.Subscribe(subs["applied"], func(msg *nats.Msg) {
		var evt ampyconfig.ConfigApplied
		_ = json.Unmarshal(msg.Data, &evt)
		fmt.Printf("[go-service] ConfigApplied change_id=%s status=%s\n", evt.ChangeID, evt.Status)
		if evt.Status == "ok" {
			time.Sleep(100 * time.Millisecond)
			n, err := ld.Load()
			if err != nil {
				fmt.Printf("[go-service] reload error: %v\n", err)
				return
			}
			val, _ := ampyconfig.GetInt(n, "oms", "risk", "max_order_notional_usd")
			fmt.Printf("[go-service] reloaded max_order_notional_usd=%d\n", val)
		}
	})
	if err != nil { panic(err) }

	_, _ = client.Subscribe(subs["apply"], func(msg *nats.Msg) {
		var evt ampyconfig.ConfigApply
		_ = json.Unmarshal(msg.Data, &evt)
		fmt.Printf("[go-service] saw ConfigApply change_id=%s\n", evt.ChangeID)
	})
	_, _ = client.Subscribe(subs["preview"], func(msg *nats.Msg) {
		var evt ampyconfig.ConfigPreviewRequested
		_ = json.Unmarshal(msg.Data, &evt)
		fmt.Printf("[go-service] saw ConfigPreview targets=%v\n", evt.Targets)
	})

	fmt.Println("[go-service] listening… (CTRL+C to exit)")
	select {}
}
