# amazon-seller-tools

亚马逊卖家用的 AI 工具，目前只有一个：**amazon-ad-diagnosis**，用来做亚马逊稳定产品的销售下滑和广告诊断。

它按六层框架找"第一个异常的变量"：
① 市场需求 → ② 流量×转化 → ③ 自然 vs 广告 → ④ 关键词权重 → ⑤ 相对竞争力 → ⑥ 最后才看广告

执行顺序就是 SOP 顺序：**先外部（市场），再链接自身，广告最后**。外部按 trend 自动选出的主周期（周或月）和"异常起点前后"来比。链接自身先按日 → 周 → 月 → 年同比逐个周期看环比，再做跨周期对比，区分"今年真的变差 / 偏季节性 / 近期才开始 / 单日波动"（季节性看今年月环比和去年同期月环比的差，不看年同比）。年同比需要去年同期数据（`daily_ly.csv`），新品不满一年时跳过。广告诊断之后再找**关键词机会**（已出单还没开精准的收割词、自然排名 4–20 的冲刺词、竞品有而自己没有的缺口词、市场长尾词），按"相关性 → 去重 → 可承受 CPC"筛。最后把问题归为四种诊断结果之一，再给出对应的广告动作（关键词机会按诊断结果取舍：转化有问题时不加新词）、验证指标和复查计划。工具**只给建议，不改你的广告**。

## 两个版本，安装方式不同

| | Claude 版 | 通用版 |
|---|---|---|
| 给谁用 | Claude Code、Claude 桌面应用 | Codex、WorkBuddy，以及其他支持 SKILL.md 的 agent |
| 目录 | `plugins/amazon-ad-diagnosis/`（插件） | `portable/amazon-ad-diagnosis/`（skill 文件夹） |
| 安装 | 当插件装：`/plugin marketplace add` + `/plugin install` | 复制文件夹到对应软件的 skills 目录 |
| 子代理 | 拉数据、外部归因、内部归因交给子代理（按 SOP 顺序依次派） | 由 agent 自己按顺序做 |
| 详细说明 | [plugins/amazon-ad-diagnosis/README.md](plugins/amazon-ad-diagnosis/README.md) | [portable/amazon-ad-diagnosis/README.md](portable/amazon-ad-diagnosis/README.md) |

两个版本的 references（诊断规则）和 `scripts/ad_diag.py`（计算脚本）**完全相同**，差别只在入口文件和运行说明。

## 共同依赖

- **领星 ERP MCP**：拉广告和销售数据。令牌是个人的，不放进仓库，各自在自己的软件里配置。
- **西柚 MCP**（可选）：查市场、关键词和竞品数据。
- **Python 3.9+ 和 pandas 2.2+**：运行计算脚本，导出 Excel 时还需要 openpyxl。一次装好：`python -m pip install -r plugins/amazon-ad-diagnosis/skills/amazon-ad-diagnosis/scripts/requirements.txt`（Mac / Linux 用 `python3`）。已实测 pandas 2.2.3 和 3.0.1。
- **ASIN 资料**：存在 skill 自己的 `data/asin-profiles.md` 里（每个 ASIN 的成本、目标 ACOS、竞品），跟着 skill 文件夹走，不用环境变量。`data/` 被 git 忽略，不会提交；仓库里只有模板 `references/asin-profiles.md`。

## 维护（改 skill 的人看）

- **只改源目录** `plugins/amazon-ad-diagnosis/skills/amazon-ad-diagnosis/`。通用版是用脚本生成的，不要手改 `portable/` 下的文件。通用版独有的两个文件在 `tools/portable/`。
- 改完后执行：
  ```bash
  python tools/build_portable.py           # 重新生成通用版
  ```
  ```bash
  python tools/build_portable.py --check   # 提交前检查
  ```
  检查内容：通用版是否和源同步、两处版本号是否一致、有没有私有数据（ASIN 记录、邮箱、令牌、本机路径），并跑一遍冒烟测试（`tools/smoke_test.py`：用合成数据把两份脚本的 6 个子命令、SOP 门禁和边界情况都跑一遍，不用任何真实数据）。
- 每次发布，要把 `plugins/amazon-ad-diagnosis/.claude-plugin/plugin.json` 和 `.claude-plugin/marketplace.json` 的 version 一起加 1。
