package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/nats-io/nats.go"
	"gopkg.in/yaml.v3"
)

/* ---------- shared utils ---------- */

func dotSubject(topicPrefix, tail string) string {
	p := strings.ReplaceAll(topicPrefix, "/", ".")
	return fmt.Sprintf("%s.control.v1.%s", p, tail)
}

func mustReadYAML(path string) map[string]any {
	b, err := os.ReadFile(path)
	if err != nil {
		fmt.Fprintf(os.Stderr, "[ERROR] reading YAML file %q: %v\n", path, err)
		os.Exit(2)
	}
	var m map[string]any
	if err := yaml.Unmarshal(b, &m); err != nil {
		fmt.Fprintf(os.Stderr, "[ERROR] parsing YAML %q: %v\n", path, err)
		os.Exit(2)
	}
	return m
}

/* ---------- payloads (match Python) ---------- */

type ApplyPayload struct {
	ChangeID       string                 `json:"change_id"`
	CanaryPercent  int                    `json:"canary_percent"`
	CanaryDuration string                 `json:"canary_duration"`
	GlobalDeadline *string                `json:"global_deadline,omitempty"`
	Overlay        map[string]any         `json:"overlay,omitempty"`
	RunID          *string                `json:"run_id,omitempty"`
	Producer       string                 `json:"producer"`
}

type AppliedEvent struct {
	ChangeID    string   `json:"change_id"`
	Status      string   `json:"status"` // "ok" | "rejected"
	EffectiveAt string   `json:"effective_at"`
	Errors      []string `json:"errors"`
	Service     string   `json:"service"`
	RunID       *string  `json:"run_id,omitempty"`
}

type PreviewPayload struct {
	Targets   []string              `json:"targets"`
	Candidate map[string]any        `json:"candidate"`
	ExpiresAt string                `json:"expires_at"` // ISO-8601 Z
	Reason    *string               `json:"reason,omitempty"`
	RunID     *string               `json:"run_id,omitempty"`
	Producer  string                `json:"producer"`
}

type SecretRotatedPayload struct {
	Reference string  `json:"reference"`
	RotatedAt string  `json:"rotated_at"` // ISO-8601 Z
	Rollout   string  `json:"rollout"`    // "staged" | "global"
	Deadline  *string `json:"deadline,omitempty"`
	Producer  string  `json:"producer"`
}

/* ---------- subcommands ---------- */

func subApply(args []string) {
	fs := flag.NewFlagSet("apply", flag.ExitOnError)

	var (
		natsURL     string
		topic       string
		overlayFile string
		waitApplied bool
		timeoutSec  int
		runtimePath string
		runID       string
	)

	fs.StringVar(&natsURL, "nats", os.Getenv("NATS_URL"), "NATS URL (e.g. nats://127.0.0.1:4222)")
	fs.StringVar(&topic, "topic", "ampy/dev", "topic prefix (e.g. ampy/dev)")
	fs.StringVar(&overlayFile, "overlay-file", "", "YAML overlay for ConfigApply (required)")
	fs.BoolVar(&waitApplied, "wait-applied", false, "wait for matching ConfigApplied")
	fs.IntVar(&timeoutSec, "timeout", 20, "timeout (seconds) when waiting for applied")
	fs.StringVar(&runtimePath, "runtime", "runtime/overrides.yaml", "effective runtime path (informational)")
	fs.StringVar(&runID, "run-id", "", "optional run id")

	_ = fs.Parse(args)

	if natsURL == "" {
		natsURL = "nats://127.0.0.1:4222"
	}
	if overlayFile == "" {
		fmt.Fprintln(os.Stderr, "[ERROR] -overlay-file is required for apply")
		os.Exit(2)
	}

	changeID := "chg_" + time.Now().UTC().Format("20060102_150405")
	applySubject := dotSubject(topic, "config_apply")
	appliedSubject := dotSubject(topic, "config_applied")

	overlay := mustReadYAML(overlayFile)
	if len(overlay) == 0 {
		fmt.Fprintln(os.Stderr, "[ERROR] overlay is empty")
		os.Exit(2)
	}

	var runIDPtr *string
	if runID != "" {
		runIDPtr = &runID
	}

	payload := ApplyPayload{
		ChangeID:       changeID,
		CanaryPercent:  0,
		CanaryDuration: "0s",
		Overlay:        overlay,
		RunID:          runIDPtr,
		Producer:       "ops-go@1",
	}
	data, _ := json.Marshal(payload)

	nc, err := nats.Connect(natsURL, nats.Name("ampyconfig-ops-apply"))
	if err != nil {
		fmt.Fprintf(os.Stderr, "[ERROR] connect NATS: %v\n", err)
		os.Exit(2)
	}
	defer nc.Drain()

	if err := nc.Publish(applySubject, data); err != nil {
		fmt.Fprintf(os.Stderr, "[ERROR] publish: %v\n", err)
		os.Exit(2)
	}
	_ = nc.Flush()
	fmt.Printf("[ops-go] published to %s (change_id=%s)\n", applySubject, changeID)

	if !waitApplied {
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(timeoutSec)*time.Second)
	defer cancel()

	sub, err := nc.SubscribeSync(appliedSubject)
	if err != nil {
		fmt.Fprintf(os.Stderr, "[ERROR] subscribe %s: %v\n", appliedSubject, err)
		os.Exit(2)
	}
	defer sub.Unsubscribe()

	for {
		msg, err := sub.NextMsgWithContext(ctx)
		if err != nil {
			fmt.Fprintf(os.Stderr, "[ERROR] timed out waiting for ConfigApplied (change_id=%s)\n", changeID)
			os.Exit(2)
		}
		var evt AppliedEvent
		if err := json.Unmarshal(msg.Data, &evt); err != nil {
			continue
		}
		if evt.ChangeID != changeID {
			continue
		}
		if strings.ToLower(evt.Status) == "ok" {
			fmt.Printf("[OK] applied confirmed (change_id=%s) — runtime=%s\n", changeID, runtimePath)
			return
		}
		fmt.Fprintf(os.Stderr, "[ERROR] apply rejected (change_id=%s): %v\n", changeID, strings.Join(evt.Errors, "; "))
		os.Exit(1)
	}
}

func subPreview(args []string) {
	fs := flag.NewFlagSet("preview", flag.ExitOnError)

	var (
		natsURL     string
		topic       string
		overlayFile string
		targets     string
		expiresAt   string
		reason      string
		runID       string
	)

	fs.StringVar(&natsURL, "nats", os.Getenv("NATS_URL"), "NATS URL")
	fs.StringVar(&topic, "topic", "ampy/dev", "topic prefix (e.g. ampy/dev)")
	fs.StringVar(&overlayFile, "overlay-file", "", "YAML candidate overlay (required)")
	fs.StringVar(&targets, "targets", "", "comma-separated dotted keys (optional)")
	fs.StringVar(&expiresAt, "expires-at", "", "ISO-8601 Z expiry (required)")
	fs.StringVar(&reason, "reason", "", "optional reason")
	fs.StringVar(&runID, "run-id", "", "optional run id")
	_ = fs.Parse(args)

	if natsURL == "" {
		natsURL = "nats://127.0.0.1:4222"
	}
	if overlayFile == "" || expiresAt == "" {
		fmt.Fprintln(os.Stderr, "[ERROR] -overlay-file and -expires-at are required for preview")
		os.Exit(2)
	}

	candidate := mustReadYAML(overlayFile)
	if len(candidate) == 0 {
		fmt.Fprintln(os.Stderr, "[ERROR] candidate overlay is empty")
		os.Exit(2)
	}

	var ts []string
	if strings.TrimSpace(targets) != "" {
		for _, t := range strings.Split(targets, ",") {
			if s := strings.TrimSpace(t); s != "" {
				ts = append(ts, s)
			}
		}
	}

	var reasonPtr *string
	if reason != "" {
		reasonPtr = &reason
	}
	var runIDPtr *string
	if runID != "" {
		runIDPtr = &runID
	}

	payload := PreviewPayload{
		Targets:   ts,
		Candidate: candidate,
		ExpiresAt: expiresAt,
		Reason:    reasonPtr,
		RunID:     runIDPtr,
		Producer:  "ops-go@1",
	}
	data, _ := json.Marshal(payload)

	subject := dotSubject(topic, "config_preview")
	nc, err := nats.Connect(natsURL, nats.Name("ampyconfig-ops-preview"))
	if err != nil {
		fmt.Fprintf(os.Stderr, "[ERROR] connect NATS: %v\n", err)
		os.Exit(2)
	}
	defer nc.Drain()

	if err := nc.Publish(subject, data); err != nil {
		fmt.Fprintf(os.Stderr, "[ERROR] publish: %v\n", err)
		os.Exit(2)
	}
	_ = nc.Flush()
	fmt.Printf("[ops-go] published preview → %s\n", subject)
}

func subSecretRotated(args []string) {
	fs := flag.NewFlagSet("secret-rotated", flag.ExitOnError)

	var (
		natsURL   string
		topic     string
		ref       string
		rotatedAt string
		rollout   string
		deadline  string
	)

	fs.StringVar(&natsURL, "nats", os.Getenv("NATS_URL"), "NATS URL")
	fs.StringVar(&topic, "topic", "ampy/dev", "topic prefix (e.g. ampy/dev)")
	fs.StringVar(&ref, "reference", "", "secret reference (required)")
	fs.StringVar(&rotatedAt, "rotated-at", "", "ISO-8601 Z timestamp (required)")
	fs.StringVar(&rollout, "rollout", "staged", "staged|global")
	fs.StringVar(&deadline, "deadline", "", "optional ISO-8601 Z")
	_ = fs.Parse(args)

	if natsURL == "" {
		natsURL = "nats://127.0.0.1:4222"
	}
	if ref == "" || rotatedAt == "" {
		fmt.Fprintln(os.Stderr, "[ERROR] -reference and -rotated-at are required for secret-rotated")
		os.Exit(2)
	}

	var deadlinePtr *string
	if strings.TrimSpace(deadline) != "" {
		deadlinePtr = &deadline
	}

	payload := SecretRotatedPayload{
		Reference: ref,
		RotatedAt: rotatedAt,
		Rollout:   rollout,
		Deadline:  deadlinePtr,
		Producer:  "ops-go@1",
	}
	data, _ := json.Marshal(payload)

	subject := dotSubject(topic, "secret_rotated")
	nc, err := nats.Connect(natsURL, nats.Name("ampyconfig-ops-secret-rotated"))
	if err != nil {
		fmt.Fprintf(os.Stderr, "[ERROR] connect NATS: %v\n", err)
		os.Exit(2)
	}
	defer nc.Drain()

	if err := nc.Publish(subject, data); err != nil {
		fmt.Fprintf(os.Stderr, "[ERROR] publish: %v\n", err)
		os.Exit(2)
	}
	_ = nc.Flush()
	fmt.Printf("[ops-go] published secret_rotated → %s\n", subject)
}

/* ---------- main & usage ---------- */

func usage() {
	fmt.Println(`ampyconfig-ops <subcommand> [flags]

Subcommands:
  apply            Publish ConfigApply (supports -wait-applied)
  preview          Publish ConfigPreviewRequested
  secret-rotated   Publish SecretRotated

Examples:
  ampyconfig-ops apply -nats "$NATS_URL" -topic ampy/dev -overlay-file /tmp/overlay.yaml -wait-applied -timeout 20
  ampyconfig-ops preview -nats "$NATS_URL" -topic ampy/dev -overlay-file /tmp/partial.yaml -expires-at 2025-12-31T23:59:59Z
  ampyconfig-ops secret-rotated -nats "$NATS_URL" -topic ampy/dev -reference aws-sm://ALPACA_SECRET?versionStage=AWSCURRENT -rotated-at 2025-09-08T17:00:00Z
`)
}

func main() {
	// Back-compat: if no subcommand (or first arg is a flag), treat it as "apply"
	if len(os.Args) < 2 || strings.HasPrefix(os.Args[1], "-") {
		subApply(os.Args[1:])
		return
	}

	switch os.Args[1] {
	case "apply":
		subApply(os.Args[2:])
	case "preview":
		subPreview(os.Args[2:])
	case "secret-rotated":
		subSecretRotated(os.Args[2:])
	case "help", "-h", "--help":
		usage()
	default:
		fmt.Fprintf(os.Stderr, "[ERROR] unknown subcommand %q\n\n", os.Args[1])
		usage()
		os.Exit(2)
	}
}
