# 通用版运行说明（Codex / WorkBuddy / 其他 agent）

references 里的文件是和 Claude 版共用的，里面有一些 Claude 专用的说法。在你这里按下表替换。

## 说法对照

| references 里写的 | 你在这里怎么做 |
|---|---|
| 派子代理 / Agent 工具 / `subagent_type` / "同一条消息里派两个" | 你自己按 SOP 顺序做：第 2 步外部 → 第 3 步 ②③ → 第 4 步内部 → 第 5 步广告 → 第 6 步关键词机会。模板里"你的任务…"那一段就是写给你的要求。做完一项就把结果写进模板要求的文件，再做下一项 |
| 主代理 / 子代理"只回传…" | 都是你自己。明细写进文件，对话里只留结论 |
| 子代理不能问用户，问题带回来由主代理统一问 | 照做：把问题先记在文件里，第 6 步（关键词机会）结束后**一次问完** |
| AskUserQuestion（选择题） | 用一条消息问：问题编号，每题列出选项（如 A/B/C），然后**停下来等回答** |
| ToolSearch / "延迟加载" / `select:` | 不需要。MCP 工具直接在你的工具列表里，按名字找 |
| `mcp__<ID>__help / search / action` | 领星 MCP 的三个工具。在你这里名字可能是 `lingxing.help`、`mcp__lingxing__help` 等，按 help / search / action 认。用法相同：先 help 找 toolId，再 search 看字段，最后 action 执行。只调用 toolType=read 的工具 |
| `mcp__<ID>__get_asin_keywords` 等 | 西柚 MCP 的工具，按工具名后半段认。每次调用都要填 user_task（用户原话，逐字）和 intent_summary |
| `${CLAUDE_SKILL_DIR}` / Base directory / `<skill目录>` | 本 skill 的文件夹，也就是 SKILL.md 所在目录的绝对路径 |
| `claude mcp add …` | 见下面的"配置 MCP"，按你所在的软件来 |
| `~/.claude/...`、插件安装副本、`/plugin ...` | 和你无关，忽略 |

## 配置 MCP（找不到领星 / 西柚时告诉用户）

令牌、密码一律由用户自己填。你只给出步骤，或者生成带占位符的命令。

- **Codex**：令牌放在环境变量里（例如 `LINGXING_MCP_TOKEN`，由用户自己设），命令里只引用变量名：
  ```bash
  codex mcp add lingxing --url "<领星提供的 MCP 地址>" --bearer-token-env-var LINGXING_MCP_TOKEN
  ```
  领星要求的认证方式不是 Bearer 时，在 `~/.codex/config.toml` 的 `[mcp_servers.lingxing]` 下按领星文档配置请求头。西柚同理，名称用 `xiyou`。配完重启 Codex，用 `codex mcp list` 确认。
  - 注意：`codex exec` 这种非交互运行方式下，MCP 调用默认会被拒绝，要在交互模式里使用，并逐个批准。
- **WorkBuddy**：在"连接器"里添加。领星或西柚有现成连接器的直接开启；没有的，用"自定义连接器 / MCP"填地址和令牌。配完重启。
- **其他 agent 软件**：按该软件的 MCP 配置文档添加。名称建议叫 `lingxing`、`xiyou`。

暂时不想配置时，可以从卖家后台或领星手动导出报表给你：
- 广告活动日报，近 60 天
- 业务报告按日期，近 60 天，含 Sessions
- 搜索词报告，近 7 天加前 7 天

你把它们转成 `lingxing-data-pull.md` 规定的 CSV 列名，放进 `<skill目录>/data/ad-data/<ASIN>_<截止日>/`。

## 让 data/ 可写（Codex 等有沙箱的软件）

资料和数据都在 skill 自己的 `data/` 里。skill 装在工作区以外（如 `~/.agents/skills/`）或沙箱把 `.agents/` 当成项目外时，写入会被拒绝。让用户选一种：
- **一次配好（推荐）**：在 `~/.codex/config.toml` 里加
  ```toml
  [sandbox_workspace_write]
  writable_roots = ["<skill目录>/data"]
  ```
  （Windows 路径写成 `C:\\Users\\<你>\\.agents\\skills\\amazon-ad-diagnosis\\data`），重启 Codex。
- **每次启动时加**：`codex --add-dir "<skill目录>/data"`（`codex exec` 同样支持 `--add-dir`；`codex exec resume` 不支持，要用 `-c`）。
- **用 `-c` 临时覆盖时**，路径用 TOML 单引号字符串，反斜杠不用转义，也不会被 shell 改坏：
  `-c "sandbox_workspace_write.writable_roots=['C:\Users\<你>\.agents\skills\amazon-ad-diagnosis\data']"`
- 其他软件：在它的权限 / 沙箱设置里把这个目录加为可写。

**Windows 上的限制**：skill 装在项目里（`<项目>/.agents/skills/`）时，`.agents` 是沙箱的只读区，它下面的 `data/` **没法设成可写**，硬配 writable_roots 反而会让沙箱里所有命令失效。这种情况只能改用**全局安装**（`~/.agents/skills/`）再配 writable_roots。

写入失败时停下来告诉用户，**不要**改写到工作区或别处，**不要**跳过脚本、自己手算代替。**已经配过 writable_roots / --add-dir 还是失败**：不要再让用户加同一个配置，直接说明"项目级安装在 Windows 上不能写 data/，请改用全局安装"。

## ASIN 资料文件

`asin-profiles.md` 记着用户的成本和竞品，是**私有数据**，只放在 skill 自己的文件夹里：
- 读写 `<skill目录>/data/asin-profiles.md`。不存在时，把 `<skill目录>/references/asin-profiles.md`（模板）复制过去再用。
- **不要**写进 `references/` 的模板，也不要写到工作目录、用户目录或其他任何地方，不要设环境变量。

## 弱模型容易出错的地方（逐条自查）

1. 只看本周就下结论。**周、月方向相反时，两个都要写**，月度下滑是主线。
2. 用户说"我改过 X"，直接当成事实。**先到 op_log.csv 找对应的日期和活动**，对不上就问。
3. 西柚拿不到时跳过"跟没跟大盘走"。**表照样输出**，填"缺数据 / 无法判定"，并问用户具体问题。
4. 用示例参数，比如 `--target-acos 0.25`。**一律用 asin-profiles.md 里的目标 ACOS**。
5. 报告只给摘要。**完整报告要写在对话里**，同时存成 report.md。
6. 去桌面、其他应用、浏览器里找报表。**不允许**，只用 MCP、工作目录和用户上传的文件。资料文件也不要用 rg 或递归搜索去找，直接读 `<skill目录>/data/asin-profiles.md`。
7. 截止日缺数据时，随手把 `--date` 往前挪。**按 trend 的提示做**：提示不要挪就不要挪，否则月环比会算不出来。
8. 把搜索词报表的 ACOS 当成整体 ACOS。整体 ACOS、TACOS 以 trend 的输出（daily.csv）为准，搜索词 ACOS 只在第⑥层用。
9. 自己读数时把方向读反，比如"自然 −X%、广告 −Y%"、X 比 Y 大，却写成"自然没怎么降"。写结论前，把每个结论和它引用的数字对照一遍。
10. 跳过外部 / 内部归因（第 2、4 步）。没有 MCP 也要写 `rootcause_external.md` 和 `rootcause_internal.md`，缺的数据就标"缺数据"。
11. 说"文件不存在 / 数据缺失"，其实文件就在数据目录里。说缺失之前先列清单、用 Test-Path 检查，并写清楚是哪个字段、哪几天。
12. 先看广告再看外部。**按 SOP：外部（①）先下结论，广告（⑥）最后**；terms / filter 等 ④⑤ 写完才跑，高 ACOS 词不能拿来改变前面各层的结论。
13. 写入 `data/` 被拒后，把文件写到工作区、或跳过 terms / filter 自己手算。**不允许**：停下来，按"让 data/ 可写"告诉用户。
14. 跨周期表只抄总订单一行、或改写解读。**整张照抄**，补充写在表下。
15. shell 被沙箱拦住时，借 node_repl、浏览器等插件绕过沙箱去读文件、跑脚本。**不允许**：停下来，把报错原文告诉用户。
