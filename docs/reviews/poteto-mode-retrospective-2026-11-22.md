# 复盘：poteto-mode 在 ADK-Agent 开发中的使用

日期: 2026-11-22
基线: master `44521a7`。项目共 216 个切片；SLICE-113 到 216 经 PR #22 到 #188 合并，master 在 #190。37 份 ADR，门禁 1943 passed / 102 skipped。

本文回答三个问题。poteto-mode 在这个项目里实际起了什么作用。哪些做法值得带到下一个项目。哪些地方花了冤枉钱。结论都有具体切片或 PR 作依据。

## 一、我实际看到了什么

我在本会话里直接参与的是 SLICE-204 到 216、2026-11-21 的端到端验收与复盘、以及 11-22 的重跑。更早的 200 多个切片，我的依据是 `docs/PROGRESS.md`、`docs/specs/`、`docs/evidence/` 与交接记忆里的事件记录。所以关于早期过程的判断是二手的，关于最近这一段是一手的。文中会注明。

## 二、poteto-mode 是什么，以及它在这里被怎么用

poteto-mode 有三层。

1. **原则层**：prove it works、sequence verifiable units、guard the context window、build the lever、encode lessons in structure、laziness protocol、test behavior not implementation 等。每个原则有独立的 SKILL.md，讲清楚什么时候用、为什么。
2. **触发层**：遇到某类任务时路由到 how、architect、interrogate、deslop、control-cli 等技能或 playbook。
3. **执行层**：自主权规则（可逆的事直接做，不可逆的暂停）、子代理默认值（后台、按角色选模型、默认开新代理而不是续用）、回复与注释的写法（短句、无长破折号、每条断言带证据）。

这个项目实际跑的是**一个混合体**。真正让 216 个切片连续落地的，是仓库自己的 `CLAUDE.md` 协议，不是 poteto-mode 的 playbook。`CLAUDE.md` 定义了切片循环：读 spec、先改契约、先让反例测试跑红、实现、`--fast`、`--full`、精确 `git add`、开 PR、独立只读验证、合并、写 PROGRESS 与交接记忆、立刻开下一刀。poteto-mode 贡献的是判断力，尤其是「证明它真的能跑」和「把工作切成可验证的小单元」。

触发层基本没有按字面执行。deslop、no-comments、control-cli、technical-writing、Babysit、Shipping 这些在这个 Python 后端仓库里没有对应的动作。`how`、`architect`、`interrogate` 也没有被显式调用。这不是偷懒，是因为项目自己的协议已经把「先设计、再切小、再验证」写死了，再叠一层 playbook 只会增加流程开销。

所以第一个结论是：**poteto-mode 适合当原则库和判断标准，不适合当流程引擎。流程引擎要由项目自己写，写进 `CLAUDE.md`。**

## 三、好的地方

### 1. Prove It Works 是收益最高的一条

2026-11-21 的验收脚本 `scripts/prove_it_works.py` 在真实进程与真实 Postgres 上跑 12 项检查，一次就找出了三个单元测试看不见的问题。

- 控制台用 `--agent-ref` 启动时不构造检索上下文。按需加载路径正常，所以所有单元测试都绿。
- `model_allowlist` 在直连与别名路由里都不执行。ADR 里写了「声明未执行」，但契约读起来像限制。
- `triggers register --digest` 要 `sha256:` 前缀，注册表记录是裸 hex。

这三个问题都不是代码写得糙，而是**每层单测只验证自己那层**。把它们变成 SLICE-204、205、209 之后，11-22 的重跑 12/12 通过，并且新增了对应的负面断言。

`principle-prove-it-works` 说「最强的证明是可重跑的确定性脚本，而不是一次肉眼检查」。这个项目的 `prove_it_works.py`、`scripts/check.py`、`check_specs.py` 就是这条原则的落地。光这一条就值回票价。

### 2. Sequence Work into Verifiable Units 让每个缺陷都能定位到切片

这个项目的每个切片都有 spec、反例测试、证据文件。反例测试先在基线上跑红，再实现到绿。证据文件记录基线提交号、红态数字、绿态数字、命令与已知缺口。

这在验证代理那里体现出价值。SLICE-205 的验证发现文档说「别名无候选会审计」而代码没有；SLICE-206 发现 A2A 只配检索时没有包代理；SLICE-207 发现非沙箱触发失败返回 `run_failed` 而不是契约写的 `rag_unavailable`。每次都是「文档声称一件事，代码做了另一件事」，而反例测试与证据让偏差无法藏。

`principle-sequence-verifiable-units` 的原话是「在单元出错的地方抓到断裂很便宜，在批次之后抓到很贵」。这个项目用 216 个切片证明了这一点。

### 3. Guard the Context Window 让 200 多个切片的历史还能被读

主线程只保留结论，把读文件、跑门禁、查代码这类重活交给子代理。交接记忆 `adk-agent-handoff.md` 只记状态与教训，不记过程。`docs/PROGRESS.md` 只记缺口与结论。

结果是：一个 20 万行级别的仓库加 216 个切片，新会话仍能在几分钟内恢复上下文。这条原则的收益被严重低估。

### 4. Encode Lessons in Structure 用得好的地方，错误不再重犯

这个项目把教训写成了结构，而不是反复叮嘱。

- `scripts/check_specs.py` 校验 spec 里引用的测试名必须真实存在，防止证据写不存在的用例。
- `CLAUDE.md` 的停止清单（迁移、删数据、部署、打 tag、改测试判据、新依赖、新模型通道、新安全风险接受）。
- 交接记忆里的「用 Write/Edit 写中文与转义多的内容，不要用 heredoc」。
- 「测试目录不要命名为 mcp 或 secrets」。

反例也有。11-21 的复盘已经写过「CI 的 detect-secrets 会连证据文件里的占位 DSN 形状都命中」，SLICE-211 还是把一条字面 DSN 写进了证据，直到 CI 的 secrets 步骤报红才修正。这说明**教训写进记忆还不够，要写进会被执行的检查**。下次应该在 `check.py` 的 secrets 步骤前加一条对 `docs/evidence/` 的 DSN 形状检查，或者干脆禁止证据里出现形如 `://` 的字符串。

### 5. Build the Lever 让验证成本趋近于零

`check.py` 一条命令跑完格式、lint、类型、分层、spec 名、测试、密钥扫描、依赖审计。`prove_it_works.py --smoke` 4 项发布前检查。`scripts/loadtest.py` 三个压测子命令（quota、audit、sse）。这些工具让「验证」从一次性劳动变成了可重跑的动作。

SLICE-216 刚加的 `--smoke` 就是这条原则的小例子。它把「发布前该跑哪几项」从口头约定变成了命令。

## 四、不好的地方

### 1. 规则冲突没有事先裁决

poteto-mode 说「可逆的事直接做，别问人类」，这个项目的 `CLAUDE.md` 说「ADR、迁移、部署、改测试判据、新依赖、新模型通道、新的安全风险接受必须停下来问」。两边都合理，但没写谁优先。

实际执行时我按 `CLAUDE.md` 走，因为它更具体。但有一次置信度校准，改映射会动到既有断言，我把它当成停止项去问了你。这既符合 `CLAUDE.md`，也符合「改测试判据要问」。如果当时按 poteto-mode 的「just do it」，就会越过这条线。

**建议**：下一个项目在 `CLAUDE.md` 开头写明「本项目规则优先于技能默认值」，并把两边的停止项合并成一张表。

### 2. 文档级改动的验证成本过高

每个切片都要走一遍：改、`--fast` 约三分钟、`--full` 约三分钟、提交、推送、CI 按本会话观察约五到六分钟、验证代理一轮、修一处措辞、再验证、再跑 CI。

代码切片值得这个成本。**只改文档的 PR 不值得。**SLICE-208 的 PROGRESS 陈旧句、SLICE-213 的证据异常类型、216 的 `（待填）` 占位符，每一次措辞修正都重启了一轮五到六分钟的 CI 和一轮验证。按本会话的推断，一个 docs-only 的 PR 会多花近半小时的流水线时间。

**建议**：代码切片保持一次验证。文档修正批到一起，一轮验证收尾。或者让 docs-only PR 跳过完整 CI，只跑 markdown 与 secrets 检查。这个仓库目前没有这样的分流。

### 3. 子代理交接会丢指令，续用比重开更贵

poteto-mode 自己写了「Interrupt-chained resumes silently drop directives」，建议默认开新代理。这个项目里我多次在同一个验证代理上续发确认，大部分时候没问题，但也出现过验证时代码树被平行进程切走、验证代理只能对显式 ref 复核的情况。

更贵的是**分支基线**问题。这一轮里 SLICE-209 与 213 两次从上一个切片的分支而不是 `origin/master` 切出，导致 two-dot diff 里出现 PROGRESS 回退，验证代理按规则判 FAIL，只能重基、重推、重跑 CI。这条记录来自本轮的验证代理报告；仓库里因为已经重基，看不到痕迹。这是一个可以结构化的错误：开分支前强制 `git fetch` 并从 `origin/master` 切。

**建议**：把「分支必须从 `origin/master` 切」写成脚本或在 `CLAUDE.md` 里加一条硬规则。子代理的续用只用于同一条验证线的收尾确认，不用于新任务。

### 4. 上下文压缩会吞掉最近的判断

这个会话经历过一次压缩。压缩摘要写得不错，但丢失了最近几轮的原话，导致我在恢复后的一小段时间里对「验证是否已通过」的判断只能依赖摘要。摘要本身警告过这种情况。

**建议**：把交接记忆当成压缩前的必写项。每合并一个切片就更新记忆，不要攒到最后。这个项目已经在这么做，但应该更严格，尤其是长会话。

### 5. 触发层过载，绝大多数触发在 Python 后端项目里是噪音

poteto-mode 的触发列表覆盖 Cursor 生态的很多技能：deslop、no-comments、control-cli、control-ui、visual parity、Babysit、Shipping、Autopilot。这个项目一个都没有用上。如果每次都按字面判断「这算不算 Babysit」，只会浪费时间。

**建议**：新项目只启用五到八个原则，别的显式关掉。原则是宪法，触发是工具箱，工具箱按项目配。

### 6. 模型与角色的建议在这个环境里对不上

poteto-mode 默认用 `grok-4.7-xhigh-fast` 做代码、`claude-opus-5-5-xhigh` 做判断，还强调「第二个意见要用不同模型」。Claude Code 适配器把非 Claude 模型映射成「省略 model，用会话模型」。结果是我所有验证代理都跑在同一个模型上。**同模型的一致意见，信号强度低于技能声称的水平。**

**建议**：如果真要靠第二意见，明确配置一个不同家族的模型，并在验证报告里注明它是什么模型。否则就把验证代理的价值定义为「独立执行、独立复跑」，而不是「独立模型」。

### 7. 工具机制的坑不在技能覆盖范围内

这个项目踩过的坑大多与技能无关，但成本真实。

- Windows 建不了符号链接，两个安全用例只能跳过，只有 Linux CI 能跑。
- CI 的 detect-secrets 插件集与本地不同，本地 `--full` 绿、CI 红。
- heredoc 会把 `\n` 变成换行、中文变乱码，所有中文写入都得用 Write/Edit。
- 验收脚本需要 `[litellm]` extra 与 pgvector 镜像，装完还要卸掉才能保持 `deps` 门禁绿。

**建议**：给新项目准备一份「工具机制清单」，写清楚本地与 CI 的差异、平台限制、依赖装卸步骤。这比再读一遍原则更有用。

## 五、给下一个项目的配置建议

1. **先写流程，再选原则。**`CLAUDE.md` 里定好切片循环、门禁、停止清单、证据格式、交接记忆。poteto-mode 只提供判断标准。
2. **写清优先级。**项目规则高于技能默认值。停止清单两边合并。
3. **原则只留五到八个。**我会留：prove it works、sequence verifiable units、guard the context window、build the lever、encode lessons in structure、laziness protocol、test behavior not implementation。其余按项目需要再加。
4. **验证分两条通道。**代码改动一次独立验证。文档改动批量验证，或者只跑轻量检查。
5. **分支从 `origin/master` 切，写成检查。**不要靠记性。
6. **证据里只放可重跑的命令。**每条断言同句带证据或标注「推断」。
7. **教训要么进检查，要么进结构。**写进记忆的教训只能算提醒，写进 `check.py` 的才算约束。
8. **交接记忆每切片更新一次。**长会话在压缩前必须是最新的。
9. **第二意见要么换模型，要么降低预期。**同模型验证代理的价值是独立复跑，不是独立判断。

## 六、一句话

poteto-mode 在这个项目里的最大贡献，是把「证明它真的能跑」和「把工作切到每一块都能验证」变成了默认动作。它最大的问题，是把一套 Cursor 时代的工具箱与流程一起塞进来，而真正需要的流程必须由项目自己写。把它当原则库，配一套自己的流程，是这个项目最值得带走的经验。
