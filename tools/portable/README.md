# amazon-ad-diagnosis：通用版（Codex / WorkBuddy / 其他 agent）

这是给 **Codex、WorkBuddy 以及其他支持 SKILL.md 的 agent** 用的版本。Claude Code 和 Claude 桌面应用请用 [Claude 版插件](../../plugins/amazon-ad-diagnosis/README.md)。

它和 Claude 版用的是同一套诊断规则和计算脚本，区别有两点：
- 没有子代理，拉数据、内部归因、外部归因都由 agent 自己按顺序做；
- 多了一份 `references/portable-runtime.md`，把 Claude 专用的说法翻译成通用做法。

> 这个目录是由 `tools/build_portable.py` 自动生成的，请不要直接修改。

## 安装

先把仓库克隆到本地，再把 **`portable/amazon-ad-diagnosis` 整个文件夹**复制到对应软件的 skills 目录。文件夹名必须保持 `amazon-ad-diagnosis`。

### Codex（CLI / 桌面版）

| 安装范围 | 复制到 |
|---|---|
| 所有项目都能用 | `~/.agents/skills/amazon-ad-diagnosis/`（Windows 是 `C:\Users\<你>\.agents\skills\amazon-ad-diagnosis\`） |
| 只在某个项目里用 | `<项目目录>/.agents/skills/amazon-ad-diagnosis/` |

以 PowerShell 为例：
```powershell
Copy-Item -Recurse "<仓库路径>\portable\amazon-ad-diagnosis" "$HOME\.agents\skills\amazon-ad-diagnosis"
```

**让 skill 的 `data/` 可写（必须）**：资料和数据都存在 skill 自己的 `data/` 里，但 Codex 的沙箱默认只允许写当前工作区。在 `~/.codex/config.toml` 里加一次：
```toml
[sandbox_workspace_write]
writable_roots = ["C:\\Users\\<你>\\.agents\\skills\\amazon-ad-diagnosis\\data"]
```
**Windows 上请用全局安装**：项目级安装（`<项目>\.agents\skills\`）时 `.agents` 是沙箱只读区，`data/` 设不成可写，硬配还会让沙箱里所有命令失效。不想改配置的话，每次启动加 `codex --add-dir "<skill目录>\data"`；或者用 `-c "sandbox_workspace_write.writable_roots=['C:\Users\<你>\.agents\skills\amazon-ad-diagnosis\data']"`（路径用单引号，Windows 上双引号加反斜杠容易被 shell 改坏）。
没配的话，agent 写数据时会被拒绝并停下来提示你。

装好后重启 Codex。在对话里说"分析一下广告"，或者用 `$amazon-ad-diagnosis` 手动调用。

**连接领星和西柚**：先把令牌存进环境变量（由你自己设置），再添加 MCP：
```bash
codex mcp add lingxing --url "<领星提供的 MCP 地址>" --bearer-token-env-var LINGXING_MCP_TOKEN
```
然后用 `codex mcp list` 确认已添加。

注意：`codex exec` 这种非交互的运行方式会**自动拒绝 MCP 调用**，所以需要领星或西柚时，请在交互界面里用，并逐个批准调用。

### WorkBuddy

复制到 `~/.workbuddy/skills/amazon-ad-diagnosis/`，然后重启 WorkBuddy。领星和西柚在"连接器"里添加：有现成的连接器就直接开启；没有的话，用自定义 MCP 填写地址和令牌。

**装 pandas（必须）**：WorkBuddy 自带的 Python（`~/.workbuddy/binaries/python/envs/default/`，3.13）里有 openpyxl，**没有 pandas**，不装的话脚本一跑就报 `No module named pandas`。在 skill 文件夹里执行一次：
```powershell
& "$HOME\.workbuddy\binaries\python\envs\default\Scripts\python.exe" -m pip install -r scripts\requirements.txt
equirements.txt
```

已核实：WorkBuddy 的 skill 放在 `~/.workbuddy/skills/<名称>/`，SKILL.md 格式（name + description）和本 skill 一致。还没有在 WorkBuddy 里实际跑过一次完整诊断；它的沙箱对 skill 的 `data/` 能不能写也还没验证。

### 其他 agent

只要支持 SKILL.md（Agent Skills 格式），就把文件夹复制到它的 skills 目录。MCP 按该软件自己的方式配置。

## ASIN 资料（第一次用会自动建）

成本、目标 ACOS、竞品这些私有数据，存在 skill 文件夹自己的 **`data/asin-profiles.md`** 里，跟着文件夹走，不需要设环境变量。第一次分析时 agent 会用模板自动建好；以后每次分析都会先列出已记录的 ASIN 让你选，也可以新增。

- **更新 skill 时保留 `data/`**：用新版本覆盖旧文件夹时，不要先删掉整个文件夹。PowerShell 可以这样只覆盖其他文件：
  ```powershell
  Copy-Item -Recurse -Force "<仓库路径>\portable\amazon-ad-diagnosis\*" "$HOME\.agents\skills\amazon-ad-diagnosis\"
  ```
  仓库里的 portable 文件夹没有 `data/`，所以不会覆盖你的资料。
- 换电脑：连同 `data/` 一起拷走。

## 依赖

- Python 3.9+ 和 pandas 2.2+（导出 Excel 还要 openpyxl）：`python -m pip install -r scripts/requirements.txt`，在 skill 文件夹里执行；Mac / Linux 用 `python3`。
- 领星 ERP MCP。如果不想配，也可以把卖家后台导出的报表放进 skill 文件夹的 `data/ad-data/<ASIN>_<日期>/`。
- 西柚 MCP（可选）。没有的话，市场对照一节会标注"缺数据"。

## 使用建议

- **能力较弱的模型**（如 GPT-mini 系列、国产通用模型）可以跑完整个流程，但结论**需要人工复核**。重点核对三件事：
  - 周数据和月数据是否都看了；
  - 用户自己说的情况，有没有和操作日志核对过；
  - 报告是不是完整写在了对话里。
- 数据量大时，让 agent 分段拉取，并把中间结果写成文件。不要让它把原始 JSON 全部贴进对话。
