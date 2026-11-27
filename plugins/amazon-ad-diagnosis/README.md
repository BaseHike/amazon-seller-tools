# amazon-ad-diagnosis：Claude 版（插件）

这是给 **Claude Code** 和 **Claude 桌面应用**用的版本。Codex、WorkBuddy 等其他 agent 请用 [通用版](../../portable/amazon-ad-diagnosis/README.md)。

诊断按六层框架进行：找第一个异常的变量 → ①市场需求 → ②流量×转化 → ③自然 vs 广告 → ④关键词权重 → ⑤相对竞争力 → ⑥最后才看广告。之后找关键词机会（收割词 / 冲刺词 / 竞品缺口词 / 市场词），归为四种诊断结果之一，再匹配广告动作和验证指标。

完整流程：
1. 收集信息
2. 用子代理从领星拉数据
3. 跑 trend，得到主周期、异常起点
4. 按 SOP 顺序：外部子代理先查市场（按主周期和异常起点前后对比）→ 主代理写 ②③ 销售拆解 → 内部子代理查关键词和竞争力 → 主代理最后做广告诊断
5. 关键词机会：`harvest` 列出已出单还没开精准的词，西柚补冲刺词、竞品缺口词、市场词，过相关性和可承受 CPC 两关
6. 归类、按诊断结果取舍关键词机会、给出动作、写复查计划

报告会完整写在对话里，同时保存为 `skills/amazon-ad-diagnosis/data/ad-data/<ASIN>_<日期>/report.md`（拉下来的数据也在这个文件夹，和 ASIN 资料一样跟着 skill 走、不提交到 git）。

## 安装

1. 把仓库克隆到本地：
   ```bash
   git clone https://github.com/BaseHike/amazon-seller-tools.git
   ```
2. 在 Claude Code 里添加本地市场并安装插件。路径换成你克隆下来的目录：
   ```
   /plugin marketplace add <仓库路径>
   /plugin install amazon-ad-diagnosis@amazon-seller-tools
   ```
   也可以在终端里执行：
   ```bash
   claude plugin marketplace add "<仓库路径>"
   ```
   ```bash
   claude plugin install amazon-ad-diagnosis@amazon-seller-tools
   ```
3. **新开一个会话**，插件才会生效。skill 的名字是 `amazon-ad-diagnosis:amazon-ad-diagnosis`，在对话里说"分析一下广告"就会触发。

## ASIN 资料（第一次用会自动建）

每个 ASIN 的成本、毛利率、目标 ACOS、阶段、竞品，记在 skill 自己的 **`skills/amazon-ad-diagnosis/data/asin-profiles.md`** 里，跟着 skill 文件夹走，不用设环境变量，也不会写到别的地方。

- 第一次分析时，AI 会用模板 `references/asin-profiles.md` 自动创建它；以后每次分析都会先列出已记录的 ASIN 让你选，也可以选"新增 ASIN"。
- `data/` 已被 git 忽略，**不会推到 GitHub**，也不会被 `git pull` 覆盖。
- **推荐用本地文件夹安装**（下面"安装"的方式）：Claude 直接读写你克隆下来的这个文件夹，资料一直在里面。如果是直接从 GitHub 安装（`marketplace add BaseHike/amazon-seller-tools`），Claude 用的是安装副本，**更新插件时副本会被替换，资料会丢**——这种装法要自己定期备份 `data/`。
- 换电脑：把整个仓库文件夹（含 `data/`）拷过去，或者 clone 后把旧的 `data/asin-profiles.md` 放回同一位置。
- **拉下来的数据**也在 `data/ad-data/<ASIN>_<日期>/` 里（CSV、报告、归因文件）。原始 JSON 会在生成 CSV 后删掉，避免文件夹变大。
- **插件缓存**：Claude 每次更新插件，会把插件文件夹（包括 `data/`）复制一份到 `~/.claude/plugins/cache/amazon-seller-tools/amazon-ad-diagnosis/<版本>/`，旧版本不会自动删。用本地文件夹安装时 Claude 读的是源码文件夹，这些副本用不上，可以定期删掉旧版本的文件夹。

## 依赖

Python 3.9+ 和 pandas 2.2+（导出 Excel 还要 openpyxl），在仓库根目录执行一次：
```bash
python -m pip install -r plugins/amazon-ad-diagnosis/skills/amazon-ad-diagnosis/scripts/requirements.txt
```
Mac / Linux 上把 `python` 换成 `python3`。

## 连接领星和西柚

插件里不放 MCP 配置，因为令牌是个人的。连接方式有两种：

- **在 claude.ai 的"设置 → 连接器"里添加**：绑在你的账号上，在哪里用都能连。
- **在终端里加到全局**：
  ```bash
  claude mcp add --scope user --transport http lingxing "<领星提供的 MCP 地址>" --header "Authorization: <你的令牌>"
  ```

两个都没配置时，第 1 步会问你怎么处理：让 AI 帮你配（令牌由你自己填）、你自己配，或者先不配。先不配时，可以用现成数据或手动导出的报表。

## 更新

- **更新到仓库的新版本**：先 `git pull` 拉取最新代码，再执行：
  ```bash
  claude plugin marketplace update amazon-seller-tools
  ```
  ```bash
  claude plugin update amazon-ad-diagnosis@amazon-seller-tools
  ```
  执行完要新开会话才生效。
- **自己改了插件**：见仓库根目录 README 的"维护"一节。要升版本号，并运行 `tools/build_portable.py`。

## 排错

- 报错信息里出现 `${CLAUDE_SKILL_DIR}` 这串字：说明这个变量没有被自动替换。SKILL.md 里已经写了备用办法，AI 会自己改用加载时给出的 Base directory。
- 中文乱码：CSV 文件要用 python 以 `utf-8-sig` 编码读取，不要用 PowerShell 的 Get-Content。
