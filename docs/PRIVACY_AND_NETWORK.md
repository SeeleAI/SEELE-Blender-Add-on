# Privacy and network behavior

SEELE Transfer opens an HTTP receiver only on fixed loopback address `127.0.0.1:9878`. It never binds a LAN-facing address. Browser requests require an exact build-time SEELE Origin and a short-lived challenge bound to that Origin and receiver installation.

The release package embeds the exact production SEELE Origin and download hosts. End users cannot add wildcard Origins, broaden the host allowlist, enable development Origins or turn on the legacy Consume protocol. Feature and test Origins are not included.

The plugin receives short-lived HTTPS download grants inside a direct manifest. Grants are held in memory while the transfer is active and are not included in public status responses, diagnostics, default HTTP logs or Blender UI. The plugin does not store SEELE cookies, API keys, shared production secrets or login credentials.

Downloaded files are written below the configured sentinel-managed cache. Public status and copied diagnostics exclude manifest download URLs, tokens, cache paths and local file paths. The diagnostic summary contains receiver/host versions, port, supported protocol/formats and sanitized transfer states/errors.

When `sha256` or `sizeBytes` is supplied, it is strictly validated. A transfer missing either field may continue for compatibility, but its public status includes an integrity warning. Receiver hard byte limits remain active even when no size was declared.

CORS does not protect against a malicious native process already running on the same computer. Authorization therefore also relies on short-lived BFF grants, exact receiver/challenge binding, manifest expiry, HTTPS allowlists and file integrity checks.
