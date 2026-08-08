# SEELE Transfer for Blender 0.2.1

Blender 4.x 的本地 DCC receiver。插件接收 Code4Agent Web 投递的 `dcc-transfer.v1` direct manifest，在后台下载和校验文件，并在 Blender 主线程调用原生 importer。

当前 Code4Agent 已核验的 Web → BFF → Blender E2E 范围仅为 **Workspace FBX**。GLB、glTF 和 STL importer 会按 Blender 实际可用性显示在 health capabilities 中，但在 BFF source resolver 和真实 fixtures 完成前，不代表 Web E2E 已开放。

## 安装、升级与卸载

1. 在 Blender 打开 **Edit → Preferences → Add-ons → Install from Disk**。
2. 选择 `seele_blender-0.2.1.zip` 并启用 **SEELE Transfer**。
3. 在 3D View 按 `N`，打开 **SEELE** 页签查看 receiver 状态。

升级时先停用并删除旧插件，重启 Blender，再安装 0.2.1。卸载插件不会自动删除下载缓存；请在卸载前使用 **Clear Cache**，或在确认 sentinel 后手工处理缓存。

经典 Add-on ZIP 支持 Blender 4.0+。仓库中的 `blender_manifest.toml` 面向 Blender 4.2+ Extensions 打包流程。

## 配置

Add-on Preferences 中保留以下正式配置：

- **Production / Feature / Test Origin**：精确 `scheme://host[:port]`，禁止 `*`、credentials、path、query 和 fragment。
- **Download Host Allowlist**：逗号分隔的精确 `host` 或 `host:port`，禁止通配符。
- **Cache Directory**：默认 `~/.seele/blender-cache`。插件创建 `.seele-blender-cache` sentinel。
- **Bridge Port**：默认 `9878`；固定监听 `127.0.0.1`，无法改为 `0.0.0.0`。

修改网络配置后需要 Stop/Start Bridge。正式主链路不需要配置 BFF URL。

开发 Origin 和旧 `blender-transfer.v1` Consume 流程均默认关闭。Legacy 仅用于 0.2.x 迁移联调，并计划在 0.3.0 删除。

## 统一 Receiver API

- `GET /v1/health`
- `POST /v1/transfers`
- `GET /v1/transfers/{transferId}`
- `POST /v1/transfers/{transferId}/cancel`

Health 返回 `service=seele-dcc-receiver`、DCC/host/receiver 版本、实际 importer readiness、capabilities、一次性 challenge 及明确过期时间。Web 必须根据 `protocols` 和 `capabilities.formats` 协商，不能只根据端口判断插件类型。

Direct manifest 投递：

```json
{
  "version": "dcc-transfer.v1",
  "receiverId": "installation-id",
  "challenge": "single-use-value",
  "manifest": {
    "version": "dcc-transfer.v1",
    "transferId": "uuid",
    "target": {"dcc": "blender", "format": "fbx"},
    "receiverId": "installation-id",
    "entryFileId": "model",
    "files": []
  }
}
```

成功响应统一为 `{"ok":true,"data":...}`，错误统一为：

```json
{
  "ok": false,
  "error": {
    "code": "DOWNLOAD_HASH_MISMATCH",
    "message": "Downloaded file verification failed",
    "retryable": false,
    "stage": "verifying"
  }
}
```

本地状态为 `accepted → downloading → verifying → queued → importing_geometry → importing_materials → completed`，并支持 `cancel_pending`、`cancelled`、`completed_with_warnings` 和 `failed`。BFF `READY` 只表示授权准备完成，不代表 Blender 已导入。

## 安全与导入行为

- challenge 与 receiverId、精确 Origin 绑定，60 秒有效且只能消费一次。
- 下载只允许 HTTPS；初始 URL、每次 redirect 和最终 URL 都重新检查精确 host/port allowlist。
- `sizeBytes` 存在时严格限制并验证实际字节数，`sha256` 存在时严格执行下载后校验。字段缺失时允许兼容传输并返回完整性 warning；无论字段是否存在，文件数量、单文件大小和总下载量仍受 receiver 硬上限约束。
- 路径必须是规范化 POSIX 相对路径；拒绝绝对路径、盘符、反斜杠、`.`、`..`、控制字符和编码路径穿越。
- 下载写入独立 `<transferId>/<instanceId>/`，经 size/hash 验证后原子替换 `.part`。
- 网络和下载在线程中执行；所有 `bpy` 操作仅由主线程 timer 执行。
- 导入前记录 Blender datablock snapshot。失败或导入中取消时只回滚本次新增对象、Collection、Mesh、Material、Image、Armature 和 Action。
- 成功资产进入独立 `SEELE_<name>` Collection；自动聚焦只通过 Sidebar 的 **Frame** 按钮执行。
- STL 只使用 manifest 的 `unitScaleMeters`，不修改 Scene 全局单位。

详细隐私与网络行为见 [docs/PRIVACY_AND_NETWORK.md](docs/PRIVACY_AND_NETWORK.md)，故障处理见 [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)。

## 错误码

稳定错误包括：`INVALID_REQUEST`、`PROTOCOL_UNSUPPORTED`、`RECEIVER_MISMATCH`、`ORIGIN_BLOCKED`、`CHALLENGE_EXPIRED`、`CHALLENGE_REPLAYED`、`TRANSFER_EXPIRED`、`TRANSFER_CONFLICT`、`INVALID_MANIFEST`、`UNSUPPORTED_FORMAT`、`DOWNLOAD_HOST_BLOCKED`、`DOWNLOAD_EXPIRED`、`DOWNLOAD_HTTP_ERROR`、`DOWNLOAD_TLS_ERROR`、`DOWNLOAD_TIMEOUT`、`DOWNLOAD_NETWORK_ERROR`、`DOWNLOAD_WRITE_FAILED`、`DOWNLOAD_SIZE_MISMATCH`、`DOWNLOAD_HASH_MISMATCH`、`DEPENDENCY_MISSING`、`IMPORT_OPERATOR_UNAVAILABLE`、`IMPORT_GEOMETRY_FAILED`、`IMPORT_MATERIAL_FAILED`、`IMPORT_ROLLBACK_FAILED`、`CANCELLED` 和 `INTERNAL_ERROR`。

Web 应根据 code 和 retryable 展示本地化文案，不依赖英文 message。

## 测试

```powershell
python -m unittest discover -s tests/unit -v
```

Blender headless fixture：

```powershell
blender --background --factory-startup --python tests/blender_integration/run_import.py -- fixture.fbx
```

`tests/fixtures` 保存统一 contract 的 valid/invalid JSON fixtures，供 Python 与 Code4Agent TypeScript validator 对齐。发布前仍必须完成真实 Workspace FBX、Windows/macOS、Blender 4.x、Chrome/Edge 和 Unity 旧链路回归。

## 开发边界

此仓库只实现 Blender receiver。Code4Agent 的 `/dcc-transfers`、Web adapter、Unity serializer 回归及 feature 环境 E2E 不在本仓库中，不能用插件单测替代。
