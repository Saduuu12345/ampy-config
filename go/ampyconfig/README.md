# ampyconfig (Go)

Typed config + secrets façade for AmpyFin (Go port).  
- Layering: defaults → env profile → overlays → ENV → runtime overrides  
- Secrets: refs (Vault/AWS/GCP), TTL cache, redaction, rotation signals  
- Control plane: preview/apply/confirm + secret_rotated via NATS JetStream

Install:
```bash
go get github.com/AmpyFin/ampy-config/go/ampyconfig@v0.1.1
