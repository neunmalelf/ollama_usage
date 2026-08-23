# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- Initial public release under the MIT license.
- CLI with `--json`, `--browser`, `--cookie`, `--watch`, `--alert`,
  `--quiet`, `--notify`, `--minidisplay` and `--debug` flags.
- Python library API via `ollama_usage.get_usage`.
- Auto browser cookie detection and manual cookie support.
- Web search and web fetch usage statistics and per-model request counts.
- Colored ANSI output.
- Single-line `--minidisplay` output with optional autorefresh countdown.
- Desktop notifications via the `[notify]` extra.
