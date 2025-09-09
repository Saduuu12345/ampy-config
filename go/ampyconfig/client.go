package ampyconfig

import (
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/nats-io/nats.go"
)

type Client struct {
	nc          *nats.Conn
	natsURL     string
	topicPrefix string // e.g., "ampy/dev"
	effective   string // path to effective YAML your service reads
}

func New(natsURL, topicPrefix, effectivePath string) *Client {
	if natsURL == "" {
		natsURL = os.Getenv("NATS_URL")
		if natsURL == "" {
			natsURL = "nats://127.0.0.1:4222"
		}
	}
	return &Client{
		natsURL:     natsURL,
		topicPrefix: strings.ReplaceAll(topicPrefix, "/", "."),
		effective:   effectivePath,
	}
}

func (c *Client) Connect() error {
	nc, err := nats.Connect(c.natsURL,
		nats.Name("ampy-config-go"),
		nats.Timeout(5*time.Second),
	)
	if err != nil {
		return fmt.Errorf("connect NATS: %w", err)
	}
	c.nc = nc
	return nil
}

func (c *Client) Close() { if c.nc != nil { _ = c.nc.Drain() } }

func (c *Client) Subjects() map[string]string {
	base := c.topicPrefix + ".control.v1"
	return map[string]string{
		"preview":       base + ".config_preview",
		"apply":         base + ".config_apply",
		"applied":       base + ".config_applied",
		"secretRotated": base + ".secret_rotated",
	}
}

// Direct NATS subscribe (works even if JetStream stores the same subjects).
func (c *Client) Subscribe(subject string, cb nats.MsgHandler) (*nats.Subscription, error) {
	if c.nc == nil { return nil, fmt.Errorf("not connected") }
	return c.nc.Subscribe(subject, cb)
}

// Optional queue group helper.
func (c *Client) QueueSubscribe(subject, queue string, cb nats.MsgHandler) (*nats.Subscription, error) {
	if c.nc == nil { return nil, fmt.Errorf("not connected") }
	return c.nc.QueueSubscribe(subject, queue, cb)
}
