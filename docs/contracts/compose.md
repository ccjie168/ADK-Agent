# 声明式组合契约

组合器把受控模板与参数变成普通已发布版本。用户不提交代码或文件。

## `TemplateInfo`

```json
{
  "template_id": "single-llm",
  "description": "Single LlmAgent with optional built-in ping tool",
  "parameters": [
    {"name": "name", "description": "agent id, ADK-safe", "required": true, "default": null},
    {"name": "version", "description": "version string", "required": true, "default": null},
    {"name": "tenant", "description": "tenant", "required": true, "default": null},
    {"name": "owner", "description": "owner label", "required": false, "default": null},
    {"name": "description", "description": "agent description", "required": false, "default": null},
    {"name": "instruction", "description": "system instruction", "required": true, "default": null},
    {"name": "tools", "description": "subset of [ping]", "required": false, "default": []},
    {"name": "data_classes", "description": "data classes for tool grants", "required": false, "default": []}
  ],
  "tools": ["ping"]
}
```

## 参数规则

- `name`：`^[A-Za-z_][A-Za-z0-9_]{0,63}$`。manifest 的 id 与生成的 ADK agent 名都用它。
- `version`、`tenant`：manifest 的安全名模式。
- `owner` 缺省等于 tenant；`description` 缺省是 `<name> agent.`。
- `instruction`：1 到 4000 字符。生成代码里用 `repr` 嵌入。
- `tools`：只能是 `ping`；重复项拒绝。
- `data_classes`：`public`、`internal`、`confidential`、`restricted`；选中 `ping` 时写进 `ToolGrant.data_classes` 与 `manifest.data_scopes`。
- 未知参数、未知模板、未声明的工具都拒绝。

## 生成结果

- manifest：`exposure="none"`，`execution_tier="in_process"`（平台模板生成，ADR-0024），`model_policy.provider_allowlist=["litellm"]`，无 `eval_suite`。
- 工件：确定性 zip，含 `manifest.json` 与 `agent.py`。同参数同模板得到同一 sha256。
- `agent.py` 导出 `agent` 与 `root_agent`，名字等于 manifest id。
- 发布：`enforce_eval_gate`、`published_from`、注册表 `publish`，再用工件存储或 HTTP 注册表的 `upload_artifact` 写字节。重复组合相同内容幂等；同版本不同内容冲突。

## CLI

`adk-agent templates` 输出 `[TemplateInfo]` JSON。

`adk-agent compose --template single-llm --tenant TENANT --id ID --version VERSION --instruction TEXT [--owner OWNER] [--description TEXT] [--tools LIST] [--data-classes LIST] --key FILE --key-id ID [--registry DIR] [--registry-url URL] [--artifact-dir DIR | ARTIFACT_URL]`

- `--key` 是 Ed25519 私钥 PEM 路径，`--key-id` 写进 `AgentArtifact.key_id`。平台不保存私钥。
- 文件注册表配 `--artifact-dir` 或 `ARTIFACT_URL`，二选一；`--registry-url` 时通过注册表上传字节，不能再给工件存储参数。
- 成功输出 `composed tenant/id@version sha256:<digest>` 与 `artifact sha256:<hex>`，退出 0。
- 未知模板、非法参数、非法 name、未声明工具、缺 key、存储冲突或不可达都退出 1，stderr 输出原因。
- 生成的版本与手工发布版本没有区别：评测门禁、生命周期、市场与加载规则原样适用。
