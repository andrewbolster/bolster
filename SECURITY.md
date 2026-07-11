# Security Policy

## Supported Versions

| Version | Supported |
| ------- | --------- |
| 0.7.x   | ✓         |
| \< 0.7   | ✗         |

## Reporting a Vulnerability

**Do not report security vulnerabilities through public GitHub issues.**

Use GitHub's [private vulnerability reporting](https://github.com/andrewbolster/bolster/security/advisories/new)
to submit a confidential report.

Alternatively, email [andrew.bolster@gmail.com](mailto:andrew.bolster@gmail.com) with the subject
line `[SECURITY] bolster vulnerability report`.

Please include:

- A description of the vulnerability
- Steps to reproduce the issue
- Potential impact and severity
- A suggested fix or mitigation (if known)

## Response Timeline

| Milestone         | Target     |
| ----------------- | ---------- |
| Acknowledgement   | 48 hours   |
| Initial triage    | 7 days     |
| Fix or mitigation | 90 days    |

We aim to acknowledge all reports within 48 hours and resolve confirmed vulnerabilities within
90 days. If a vulnerability cannot be fixed within that window we will communicate an updated
timeline.

## Disclosure Policy

We follow coordinated disclosure:

1. Reporter submits via private channel above.
1. We acknowledge, triage, and work on a fix.
1. A patch release is issued with the fix included.
1. A [GitHub Security Advisory](https://github.com/andrewbolster/bolster/security/advisories)
   is published with CVE details once the fix is available.
1. The reporter is credited in the release notes unless they request anonymity.

## Known Vulnerabilities in Dependencies

Dependency vulnerabilities are tracked automatically via
[Dependabot](https://github.com/andrewbolster/bolster/security/dependabot) and resolved in
routine patch releases. Fixed CVEs are noted in [CHANGELOG.md](CHANGELOG.md) under the relevant
release entry.
