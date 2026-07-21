# Runtime configuration

This directory is reserved for non-secret local configuration and documented example
settings. The versioned adapter defaults live in `training/default_config.yaml`.

Never store Hugging Face tokens, private model paths, personal data, or generated
credentials here. Use environment variables or the platform's secret store for
authentication, and keep machine-specific overrides outside Git.
