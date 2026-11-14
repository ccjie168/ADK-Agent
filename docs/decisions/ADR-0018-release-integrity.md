# ADR-0018 依赖锁定与发行完整性

状态: Accepted   日期: 2026-11-14   签字: Jie CAO（会话确认）

## 背景

现在的依赖声明是范围，不是可复现的集合：

- `pyproject.toml` 声明 `google-adk[mcp]>=2.0,<3` 等范围，CI 用 `pip install -e ".[dev,claude,http]"` 现装。
- `Dockerfile` 也从范围安装，且注释已经写明“运行时依赖还没锁，生产发布前补 lock 与 SBOM”。
- CI 只跑门禁、生成 SBOM 并上传，不构建镜像、不扫描镜像；镜像标签是 `adk-agent:latest`。
- `deploy/k8s/multi-replica.yaml` 用 `image: adk-agent:latest` 与 `imagePullPolicy: IfNotPresent`。

同一天两次 CI 可能解析出不同的传递依赖。门禁全绿证明的是“当前解析组合通过”，不是“要发布的镜像通过”。SLICE-018 Phase B 也把依赖锁、镜像扫描、SBOM 校验列为待办。

约束：

- 项目是应用镜像，不是对外发布的库；库消费者仍应使用 `pyproject.toml` 的范围。
- 开发机是 Windows，CI 与镜像是 Linux。锁必须为 Linux 生成。
- 不新增运行时依赖。锁工具只进开发依赖。

## 决定

1. **用 `pip-tools` 生成两个带哈希的锁文件，提交到仓库。**
   - `requirements/runtime.lock` 由 `.[claude,litellm,http,oidc,publish,redis]` 编译，供镜像使用。
   - `requirements/dev.lock` 由 `.[dev,claude,litellm,http,oidc,publish,redis]` 编译，供 CI 使用。
   - `litellm` 必须在镜像里。模型解析在没有 `ADK_AGENT_MODEL` 时默认回退到 LiteLLM 的 `deepseek/deepseek-v4-pro`，国内模型也走 `litellm:deepseek/<model>`。
   - 编译在 `python:3.13-slim` 容器里做，与 Docker 基础镜像一致，避免 Windows 轮子与 marker 偏差。
   - 命令固定为 `pip-compile --generate-hashes --quiet --output-file ...`。锁文件全部使用 `==` 与 `--hash=sha256:`。
   - 安装使用 `pip install --require-hashes -r <lock>`。项目自身仍用 `--no-deps` 安装。
   - `pyproject.toml` 保留范围，是升级入口；锁文件是部署契约。升级依赖必须重新编译并把两个锁的 diff 一起评审。
2. **CI 按锁安装，再跑门禁。**
   - CI 先 `pip install --require-hashes -r requirements/dev.lock`，再跑 `scripts/check.py --full --strict`。门禁里的 pip-audit 审计的就是锁定的集合。
   - CI 构建镜像，用 Trivy 扫描 `HIGH,CRITICAL` 且只报可修复项，发现即失败。
   - SBOM 继续生成并作为构建产物上传。
3. **部署按 digest，不用浮动标签。**
   - 多副本清单的镜像写成 `adk-agent@sha256:<digest>`，禁止 `:latest`。
   - digest 由发布流程在推送镜像后取得，写进清单或部署参数。本 ADR 不新增镜像仓库推送，CI 只负责构建与扫描。
4. **基础镜像按 digest 固定。**
   - `Dockerfile` 的 `FROM python:3.13-slim` 改为 `python:3.13-slim@sha256:<digest>`。更新基础镜像是显式提交，不随构建漂移。
5. **不做的事。**
   - 不引入 `uv`、Poetry 或 Conda。
   - 不做自动依赖升级机器人；升级仍是人工评审。
   - 不给库消费者发布锁文件。

## 备选与否决

- **`pip freeze` 导出开发机环境**：平台相关，无哈希，混杂本地工具；否决。
- **只锁顶层依赖**：传递依赖继续漂移；否决。
- **无哈希锁**：无法防注册表替换与中间人，`--require-hashes` 用不上；否决。
- **`uv`**：更快，但引入新的工具链与缓存语义，当前规模不值得；否决。
- **在库里也强制锁**：会让下游无法选择兼容版本；否决。
- **CI 直接推镜像并输出 digest**：更完整，但需要仓库权限与 registry 配置，超出本切片；留给发布流水线。

## 后果

- 同一锁在 Linux 上可复现；Windows 开发机仍按 `pyproject.toml` 安装，不保证逐字节一致。
- 两个锁文件需要同步维护，升级是两条编译命令加一次评审。
- `gemini` 不在默认镜像里。需要 Gemini 的部署要重新编译锁或另建镜像。LiteLLM 在默认镜像里，覆盖 DeepSeek 等国内模型；LiteLLM 的 provider 凭据（例如 `DEEPSEEK_API_KEY`）由部署方在 Secret 中提供。
- Trivy 的误报通过带到期日的忽略文件处理，忽略项需要评审。
- 基础镜像 digest 更新变成显式动作。

## 切片

- SLICE-101：两个锁文件、Dockerfile 与 CI 改造、清单 digest 占位、结构守卫测试、可复现性与镜像扫描证据。

## 确认记录

2026-11-14 会话确认。额外确认：LiteLLM 必须进运行时镜像，用于 DeepSeek 等国内模型，因此运行时锁包含 `litellm` extra。其余决定按本 ADR 采纳。
