# Troubleshooting

## Bridge shows Error

Another Blender process may be using port 9878. Fully close other Blender processes, then click Stop/Start or restart Blender. The receiver always binds `127.0.0.1:9878`; users do not configure the port.

## Origin blocked

The public package accepts only the production SEELE Origin. Feature and test environments are not included, and users cannot expand the Origin allowlist.

## Download host blocked

The allowlist is embedded and cannot be changed by users. Downloads must resolve to `static.seeles.ai` or `agent-workspace-1368252780.cos.na-ashburn.myqcloud.com`; redirect destinations are checked again. Fix the Server URL rewrite rather than asking users to weaken the allowlist.

## Challenge expired or replayed

The Web must call health again and create a new DCC transfer. Challenges expire after 60 seconds and cannot be reused.

## Download expired, size mismatch or hash mismatch

Create a new transfer through the BFF. Do not locally retry an expired or failed download. Local retry is only available after all files were verified and the Blender importer failed with a retryable error.

## Clear Cache is refused

Clear Cache only operates on a directory with the exact `.seele-blender-cache` sentinel. Home, Desktop, Documents, Downloads, drive roots, the current blend directory, Blender config directory and symlinked paths are rejected. Stop or cancel active transfers first.

## Importer unavailable

Check `/v1/health` or the Sidebar importer readiness. The advertised format list reflects operators available in the running Blender installation.

## Diagnostics

Use **Copy Diagnostics** in the Sidebar. The copied JSON is designed to omit signed URLs, tokens and local paths.
