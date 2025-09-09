package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"

	"github.com/nats-io/nats.go"
	"gopkg.in/yaml.v3"
)

type ConfigApply struct {
	ChangeID       string                 `json:"change_id"`
	CanaryPercent  int                    `json:"canary_percent"`
	CanaryDuration string                 `json:"canary_duration"`
	GlobalDeadline *string                `json:"global_deadline"`
	Overlay        map[string]any         `json:"overlay"`
	RunID          *string                `json:"run_id"`
	Producer       *string                `json:"producer"`
}

type ConfigApplied struct {
	ChangeID    string   `json:"change_id"`
	Status      string   `json:"status"` // "ok" | "rejected"
	EffectiveAt string   `json:"effective_at"`
	Errors      []string `json:"errors,omitempty"`
	Service     string   `json:"service,omitempty"`
	RunID       *string  `json:"run_id,omitempty"`
}

func main() {
	var (
		natsURL   string
		topic     string
		runtime   string
		service   string
		stream    string
		logLevel  string
	)
	flag.StringVar(&natsURL, "nats", envOr("NATS_URL", "nats://127.0.0.1:4222"), "NATS server URL")
	flag.StringVar(&topic, "topic", envOr("AMPY_TOPIC", "ampy/dev"), "Topic prefix (e.g. ampy/dev)")
	flag.StringVar(&runtime, "runtime", envOr("AMPY_CONFIG_RUNTIME", "runtime/overrides.yaml"), "Runtime overrides path to write")
	flag.StringVar(&service, "service", envOr("AMPY_CONFIG_SERVICE", "ampy-config-agent"), "Service name for durable")
	flag.StringVar(&stream, "stream", envOr("AMPY_CONFIG_STREAM", "ampy-control"), "JetStream stream name for control-plane")
	flag.StringVar(&logLevel, "log", envOr("LOG_LEVEL", "info"), "log level (debug|info)")
	flag.Parse()

	subjects := subjectsFor(topic)

	logInfo(logLevel, "starting",
		"k", "nats", "v", natsURL,
		"k", "topic", "v", topic,
		"k", "runtime", "v", runtime,
		"k", "service", "v", service,
	)

	nc, js, err := connectJetStream(natsURL)
	must(err, "connect to NATS")

	// Ensure stream exists (idempotent)
	err = ensureStream(js, stream)
	must(err, "ensure stream")

	// Subscribe to control-plane subjects with durable push consumers
	must(subscribePush(js, stream, subjects["preview"], durableFor(service, subjects["preview"]),
		func(msg *nats.Msg) {
			// Preview: just validate shape (lightweight) -> Ack
			_ = msg.Ack()
		}), "subscribe preview")

	must(subscribePush(js, stream, subjects["apply"], durableFor(service, subjects["apply"]),
		func(msg *nats.Msg) {
			var evt ConfigApply
			if err := json.Unmarshal(msg.Data, &evt); err != nil {
				logInfo(logLevel, "apply:bad-json", "k", "err", "v", err.Error())
				_ = msg.Term()
				return
			}

			status := "ok"
			var errs []string

			if len(evt.Overlay) == 0 {
				status = "rejected"
				errs = append(errs, "overlay is empty")
			} else {
				// Validate by trying to layer+write to runtime file (atomic)
				if err := applyOverlayFile(runtime, evt.Overlay); err != nil {
					status = "rejected"
					errs = append(errs, err.Error())
				}
			}

			// Publish ConfigApplied (capture ack,err properly)
			applied := ConfigApplied{
				ChangeID:    evt.ChangeID,
				Status:      status,
				EffectiveAt: time.Now().UTC().Format(time.RFC3339) + "Z",
				Errors:      errs,
				Service:     service,
				RunID:       evt.RunID,
			}
			b, _ := json.Marshal(applied)
			_, pubErr := js.Publish(subjects["applied"], b) // <-- returns (PubAck, error)
			if pubErr != nil {
				logInfo(logLevel, "publish-applied:error", "k", "err", "v", pubErr.Error())
			}
			_ = msg.Ack()
			logInfo(logLevel, "config_apply",
				"k", "change_id", "v", evt.ChangeID,
				"k", "status", "v", status,
				"k", "errors", "v", strings.Join(errs, "; "),
			)
		}), "subscribe apply")

	must(subscribePush(js, stream, subjects["secret_rotated"], durableFor(service, subjects["secret_rotated"]),
		func(msg *nats.Msg) {
			// Invalidate caches if you add one later; no-op for now
			_ = msg.Ack()
		}), "subscribe secret_rotated")

	fmt.Printf("[agent] listening on:\n  - %s\n  - %s\n  - %s\n",
		subjects["preview"], subjects["apply"], subjects["secret_rotated"])

	// Wait for signal
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, syscall.SIGINT, syscall.SIGTERM)
	<-sig

	nc.Drain()
}

func envOr(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func subjectsFor(prefix string) map[string]string {
	pfx := strings.ReplaceAll(prefix, "/", ".")
	base := fmt.Sprintf("%s.control.v1", pfx)
	return map[string]string{
		"preview":        base + ".config_preview",
		"apply":          base + ".config_apply",
		"applied":        base + ".config_applied",
		"secret_rotated": base + ".secret_rotated",
	}
}

func durableFor(service, subject string) string {
	s := strings.Map(func(r rune) rune {
		if (r >= 'a' && r <= 'z') ||
			(r >= 'A' && r <= 'Z') ||
			(r >= '0' && r <= '9') {
			return r
		}
		return '-'
	}, fmt.Sprintf("%s-%s", service, subject))
	return strings.Trim(s, "-")
}

func connectJetStream(url string) (*nats.Conn, nats.JetStreamContext, error) {
	nc, err := nats.Connect(url,
		nats.Name("ampyconfig-agent"),
		nats.MaxReconnects(-1),
	)
	if err != nil {
		return nil, nil, err
	}
	js, err := nc.JetStream(nats.PublishAsyncMaxPending(256))
	if err != nil {
		_ = nc.Drain()
		return nil, nil, err
	}
	return nc, js, nil
}

func ensureStream(js nats.JetStreamContext, name string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	// Exists?
	if _, err := js.StreamInfo(name, nats.Context(ctx)); err == nil {
		return nil
	}
	// Create (subjects cover dev/paper/prod)
	cfg := &nats.StreamConfig{
		Name:       name,
		Subjects:   []string{"ampy.*.control.v1.*"},
		Retention:  nats.LimitsPolicy,
		MaxAge:     24 * time.Hour,
		MaxMsgs:    10_000,
		MaxBytes:   100 * 1024 * 1024,
		Storage:    nats.FileStorage,
		Discard:    nats.DiscardOld,
		NoAck:      false,
		AllowRollup: true,
	}
	_, err := js.AddStream(cfg, nats.Context(ctx))
	return err
}

func subscribePush(js nats.JetStreamContext, stream, subject, durable string, cb func(*nats.Msg)) error {
	// Auto-create / bind a durable, filtered, manual-ack push consumer
	_, err := js.Subscribe(subject, cb,
		nats.Durable(durable),
		nats.ManualAck(),
		nats.DeliverAll(),
		nats.AckExplicit(),
		nats.BindStream(stream),
	)
	return err
}

// applyOverlayFile merges overlay into existing runtime YAML and writes atomically.
func applyOverlayFile(runtimePath string, overlay map[string]any) error {
	// read current if exists
	cur := map[string]any{}
	if b, err := os.ReadFile(runtimePath); err == nil && len(b) > 0 {
		_ = yaml.Unmarshal(b, &cur)
	}

	merged := deepMerge(cur, overlay)

	out, err := yaml.Marshal(merged)
	if err != nil {
		return fmt.Errorf("marshal merged: %w", err)
	}
	tmp := runtimePath + ".tmp"
	if err := os.MkdirAll(filepath.Dir(runtimePath), 0o755); err != nil {
		return err
	}
	if err := os.WriteFile(tmp, out, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, runtimePath)
}

func deepMerge(dst, src map[string]any) map[string]any {
	for k, v := range src {
		if vmap, ok := v.(map[string]any); ok {
			if dsub, ok2 := dst[k].(map[string]any); ok2 {
				dst[k] = deepMerge(dsub, vmap)
				continue
			}
			dst[k] = deepMerge(map[string]any{}, vmap)
			continue
		}
		dst[k] = v
	}
	return dst
}

func logInfo(level string, msg string, kv ...string) {
	// tiny structured log
	if level == "" {
		level = "info"
	}
	sb := &strings.Builder{}
	sb.WriteString("{\"level\":\"")
	sb.WriteString(level)
	sb.WriteString("\",\"msg\":\"")
	sb.WriteString(msg)
	sb.WriteString("\"")
	for i := 0; i+1 < len(kv); i += 2 {
		sb.WriteString(",\"")
		sb.WriteString(kv[i])
		sb.WriteString("\":\"")
		sb.WriteString(strings.ReplaceAll(kv[i+1], "\"", "'"))
		sb.WriteString("\"")
	}
	sb.WriteString("}")
	fmt.Println(sb.String())
}

func must(err error, context string) {
	if err != nil {
		fmt.Fprintf(os.Stderr, "[fatal] %s: %v\n", context, err)
		os.Exit(1)
	}
}
