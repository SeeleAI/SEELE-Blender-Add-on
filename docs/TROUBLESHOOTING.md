# Troubleshooting

## Bridge shows Error

Another process may be using port 9878, or the cache/network configuration may be invalid. Change the port if required, then Stop/Start Bridge. The receiver always binds `127.0.0.1`.

## Origin blocked

Enter the exact Web Origin in the matching Production, Feature or Test field. Include the scheme and non-default port. Do not add a path or wildcard. Restart Bridge after changes.

## Download host blocked

Add only the exact hostname, or `hostname:port` for a non-default HTTPS port, used by the BFF download grant. Redirect destinations must also be explicitly allowed.

## Challenge expired or replayed

The Web must call health again and create a new DCC transfer. Challenges expire after 60 seconds and cannot be reused.

## Download expired, size mismatch or hash mismatch

Create a new transfer through the BFF. Do not locally retry an expired or failed download. Local retry is only available after all files were verified and the Blender importer failed with a retryable error.

## Clear Cache is refused

Clear Cache only operates on a directory with the exact `.seele-blender-cache` sentinel. Home, Desktop, Documents, Downloads, drive roots, the current blend directory, Blender config directory and symlinked paths are rejected. Stop or cancel active transfers first.

## Importer unavailable

Check `/v1/health` or the Sidebar importer readiness. The advertised format list reflects operators available in the running Blender installation.

## Diagnostics

Use **Copy Diagnostic Summary** in the Sidebar. The copied JSON is designed to omit signed URLs, tokens and local paths.
