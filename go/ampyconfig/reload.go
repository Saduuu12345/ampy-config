package ampyconfig

import (
	"fmt"
	"os"

	"gopkg.in/yaml.v3"
)

type Loader struct {
	Path string
}

func NewLoader(path string) *Loader { return &Loader{Path: path} }

func (l *Loader) Load() (map[string]any, error) {
	b, err := os.ReadFile(l.Path)
	if err != nil {
		return nil, fmt.Errorf("read effective config: %w", err)
	}
	var m map[string]any
	if err := yaml.Unmarshal(b, &m); err != nil {
		return nil, fmt.Errorf("parse YAML: %w", err)
	}
	return m, nil
}

func GetMap(m map[string]any, path ...string) (map[string]any, bool) {
	cur := m
	for _, p := range path {
		v, ok := cur[p]
		if !ok { return nil, false }
		mv, ok := v.(map[string]any)
		if !ok { return nil, false }
		cur = mv
	}
	return cur, true
}

func GetInt(m map[string]any, path ...string) (int64, bool) {
	if len(path) == 0 { return 0, false }
	parent, ok := GetMap(m, path[:len(path)-1]...)
	if !ok { return 0, false }
	v, ok := parent[path[len(path)-1]]
	if !ok { return 0, false }
	switch t := v.(type) {
	case int64:
		return t, true
	case int:
		return int64(t), true
	case float64:
		return int64(t), true
	default:
		return 0, false
	}
}
