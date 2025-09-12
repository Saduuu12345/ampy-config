# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.4] - 2024-12-19

### Added
- **Comprehensive Documentation Overhaul**: Complete rewrite of README.md with user experience insights
- **Prerequisites Section**: Clear NATS server setup instructions with common issue warnings
- **Quick Start Examples**: Comprehensive examples for both Python and Go with validation tests
- **Integration Examples**: Practical examples for ampy-bus and ampy-proto integration
- **Configuration Validation**: Examples for required key validation and schema validation
- **Enhanced Troubleshooting**: Expanded troubleshooting section with common mistakes and solutions
- **Go Client API Reference**: Complete API documentation with usage examples
- **Debug Mode Examples**: Debug logging examples for both Python and Go
- **Health Check Commands**: Quick validation commands for NATS and configuration loading

### Improved
- **User Experience**: Documentation now prevents common 2-hour debugging sessions
- **Error Messages**: Better guidance for common configuration errors
- **Getting Started**: Clearer path from installation to working examples
- **Integration Patterns**: Real-world examples for common use cases

### Fixed
- **Documentation Gaps**: Addressed missing information that caused user confusion
- **Version References**: Updated all version references to current version

## [1.1.3] - Previous Release

### Added
- Initial release with core functionality
- Python and Go client support
- NATS/JetStream integration
- Configuration layering system
- Secret management with multiple backends
- Control plane for runtime updates

---

## Release Notes

### v1.1.4 - Documentation & Developer Experience

This release focuses on dramatically improving the developer experience through comprehensive documentation updates based on real user feedback. The README has been completely overhauled to include:

- **Clear Prerequisites**: NATS server requirements are now prominently displayed
- **Practical Examples**: Real-world integration patterns with ampy-bus and ampy-proto
- **Common Issues**: Solutions for the most frequent problems users encounter
- **Validation Guidance**: How to validate configuration and handle errors properly
- **API Reference**: Complete Go client documentation with examples

This release addresses the feedback from users who found the library easy to use but struggled with setup and common configuration issues. The documentation now provides the same level of comprehensive guidance that experienced users created, but integrated directly into the official documentation.

**Breaking Changes**: None

**Migration Guide**: No migration required. This is a documentation-only release.

**Upgrade Instructions**:
```bash
# Python
pip install --upgrade ampy-config

# Go
go get github.com/AmpyFin/ampy-config/go/ampyconfig@v1.1.4
```
