BIN_DIR := $(CURDIR)/bin

.PHONY: all build clean
all: build

build:
	mkdir -p $(BIN_DIR)
	go build -o $(BIN_DIR)/ampyconfig-listener ./cmd/ampyconfig-listener
	go build -o $(BIN_DIR)/ampyconfig-ops       ./cmd/ampyconfig-ops
	go build -o $(BIN_DIR)/ampyconfig-agent     ./cmd/ampyconfig-agent
	@ls -l $(BIN_DIR)

clean:
	rm -rf $(BIN_DIR)
