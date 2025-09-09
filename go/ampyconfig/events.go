package ampyconfig

type ConfigPreviewRequested struct {
	Targets   []string       `json:"targets"`
	Candidate map[string]any `json:"candidate"`
	ExpiresAt string         `json:"expires_at"`
	Reason    *string        `json:"reason,omitempty"`
	RunID     *string        `json:"run_id,omitempty"`
	Producer  *string        `json:"producer,omitempty"`
}

type ConfigApply struct {
	ChangeID       string         `json:"change_id"`
	CanaryPercent  int            `json:"canary_percent"`
	CanaryDuration string         `json:"canary_duration"`
	GlobalDeadline *string        `json:"global_deadline,omitempty"`
	Overlay        map[string]any `json:"overlay,omitempty"`
	RunID          *string        `json:"run_id,omitempty"`
	Producer       *string        `json:"producer,omitempty"`
}

type ConfigApplied struct {
	ChangeID    string   `json:"change_id"`
	Status      string   `json:"status"` // "ok" | "rejected"
	EffectiveAt string   `json:"effective_at"`
	Errors      []string `json:"errors,omitempty"`
	Service     string   `json:"service,omitempty"`
	RunID       *string  `json:"run_id,omitempty"`
}

type SecretRotated struct {
	Reference string  `json:"reference"`
	RotatedAt string  `json:"rotated_at"`
	Rollout   string  `json:"rollout"`
	Deadline  *string `json:"deadline,omitempty"`
	Producer  *string `json:"producer,omitempty"`
}
