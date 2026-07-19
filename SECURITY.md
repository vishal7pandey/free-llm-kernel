# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |
| < 0.1   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it
responsibly:

1. **Do not** open a public GitHub issue.
2. Email the maintainer at **vishal7pandey@example.com** with a description
   of the vulnerability, steps to reproduce, and potential impact.
3. You will receive an acknowledgment within **48 hours**.
4. A fix or mitigation will be prioritized based on severity:
   - **Critical/High**: Patch within 7 days, advisory published.
   - **Medium/Low**: Patch in next release cycle.

## Disclosure

- Vulnerabilities are disclosed via GitHub Security Advisories after a fix
  is released.
- Credit will be given to reporters unless they prefer to remain anonymous.

## Security Measures

This project implements the following security practices:

- **Secret redaction**: API keys are wrapped in `Secret` objects that redact
  in `repr`, `str`, and JSON serialization.
- **Error sanitization**: `ExecutionError._redact` strips known API key
  patterns from error messages.
- **Log scrubbing**: `LoggingExtension` redacts secrets before writing logs.
- **No hardcoded secrets**: `.env` is gitignored; `.env.example` uses
  placeholder values only.
