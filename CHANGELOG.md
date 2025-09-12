  # Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.5] - 2024-12-19

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
- **CHANGELOG.md**: Comprehensive changelog with detailed release notes

### Improved
- **User Experience**: Documentation now prevents common 2-hour debugging sessions
- **Error Messages**: Better guidance for common configuration errors
- **Getting Started**: Clearer path from installation to working examples
- **Integration Patterns**: Real-world examples for common use cases
- **Developer Onboarding**: Complete API reference and practical examples

### Fixed
- **Documentation Gaps**: Addressed missing information that caused user confusion
- **Version References**: Updated all version references to current version
- **Setup Instructions**: Clear prerequisites and common issue solutions

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

---

## Release Notes

### v1.1.5 - Documentation & Developer Experience Enhancement

This release represents a major milestone in improving the developer experience for ampy-config users. Based on comprehensive user feedback and real-world usage patterns, we've completely overhauled the documentation to address the most common pain points and provide a smooth onboarding experience.

#### 🎯 **What's New in v1.1.5**

**📚 Comprehensive Documentation Overhaul**
- Complete rewrite of README.md with 1,140+ lines of detailed guidance
- Added prominent prerequisites section highlighting NATS server requirements
- Comprehensive quick start examples for both Python and Go
- Real-world integration examples with ampy-bus and ampy-proto
- Configuration validation examples and best practices
- Enhanced troubleshooting section with common mistakes and solutions

**🔧 Developer Experience Improvements**
- Clear setup instructions that prevent common 2-hour debugging sessions
- Practical examples for common integration patterns
- Complete Go client API reference with usage examples
- Debug mode examples for both Python and Go
- Health check commands for quick validation
- Better error message guidance

**📖 New Documentation Sections**
- **Prerequisites**: Clear NATS server setup with common issue warnings
- **Quick Start**: Step-by-step examples with validation tests
- **Integration Examples**: Real-world patterns for ampy-bus and ampy-proto
- **Configuration Validation**: Required key validation and schema validation
- **Troubleshooting**: Common issues, solutions, and debug techniques
- **Go Client API Reference**: Complete API documentation
- **Health Checks**: Quick validation commands

#### 🚀 **Key Benefits**

**For New Users:**
- Clear path from installation to working examples
- No more guessing about prerequisites or setup requirements
- Comprehensive examples for common use cases
- Troubleshooting guide for the most frequent issues

**For Experienced Users:**
- Complete API reference for Go client
- Integration patterns for ampy-bus and ampy-proto
- Debug techniques and health check commands
- Best practices for configuration validation

**For Teams:**
- Consistent onboarding experience
- Reduced support burden from common issues
- Clear integration patterns for team adoption
- Comprehensive troubleshooting guide

#### 🔄 **Migration Guide**

**No Breaking Changes**: This is a documentation-only release with no API changes.

**Upgrade Instructions**:
```bash
# Python
pip install --upgrade ampy-config

# Go
go get github.com/AmpyFin/ampy-config/go/ampyconfig@v1.1.5
```

**New Users**: Follow the Quick Start section in the README for the best experience.

**Existing Users**: Review the new Integration Examples and Troubleshooting sections for improved workflows.

#### 📊 **Impact Metrics**

This release addresses feedback from users who found the library easy to use but struggled with:
- **Setup and prerequisites** (now clearly documented)
- **Common configuration errors** (now with specific solutions)
- **Integration patterns** (now with practical examples)
- **Debugging issues** (now with debug techniques and health checks)

#### 🎉 **What's Next**

This release establishes a solid foundation for future improvements. The comprehensive documentation will help us gather better feedback and identify areas for further enhancement in upcoming releases.

**Feedback Welcome**: We encourage users to provide feedback on the new documentation and suggest additional examples or improvements.

---

### v1.1.4 - Previous Release
