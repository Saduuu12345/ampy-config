# ampyconfig (Go)

Typed config + secrets façade for AmpyFin (Go port).  
- Layering: defaults → env profile → overlays → ENV → runtime overrides  
- Secrets: refs (Vault/AWS/GCP), TTL cache, redaction, rotation signals  
- Control plane: preview/apply/confirm + secret_rotated via NATS JetStream

## Installation

```bash
go get github.com/AmpyFin/ampy-config/go/ampyconfig@v1.1.4
```

The module is available through the Go proxy at `proxy.golang.org` and will be discoverable on `pkg.go.dev` once the checksum database is updated (usually within a few hours of release).

## Usage

```go
import "github.com/AmpyFin/ampy-config/go/ampyconfig"
```

See the [package documentation](https://pkg.go.dev/github.com/AmpyFin/ampy-config/go/ampyconfig) for detailed API reference.
