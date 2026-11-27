# 领星数据拉取（子代理用）

> **通用版提示**：本文件和 Claude 版共用。文中的“子代理 / 主代理”都由你自己按顺序做；AskUserQuestion、ToolSearch、Agent 工具、`claude mcp add` 等说法，按 `references/portable-runtime.md` 换成你所在软件的做法。

主代理把下面"子代理 Prompt 模板"整段复制进 Agent 工具的 prompt，替换 `{{...}}`。

---

## 子代理 Prompt 模板

```
你的任务：从领星 ERP MCP 拉取一个亚马逊 ASIN 的广告与销售数据，整理成标准 CSV 写到本地。只做数据拉取和整理，不做分析。

参数
- ASIN：{{ASIN}}（{{父体/子体}}）
- 站点：{{站点}}
- 店铺：{{店铺名，未知则写"未知"}}
- 截止日期：{{yyyy-MM-dd}}
- 输出目录：{{skill目录}}/data/ad-data/{{ASIN}}_{{截止日期}}/

领星 MCP 用法
- 工具是延迟加载的：先用 ToolSearch 搜 "help search action"（搜不到再搜 "领星""lingxing"）找到名为 mcp__<ID>__help / __search / __action 的三个工具，用 select: 一次性加载。
- toolId 会随领星版本变。每项数据先用 help 按下面写的**中文关键词**找 read 工具，括号里是 2026-11 实测可用的 toolId，只作参考；搜不到就换近义关键词，不要因为一个 toolId 不存在就放弃这项。
- 调用链：help(query=关键词) 找 toolId → search(toolId) 看入参 Schema → action 执行。每个 toolId 调 action 前都必须先 search 一次看清字段，不要猜参数。
- 只调用 toolType=read 的工具。绝对不要调用任何 write 工具（创建/修改/否定/调价）。
- 分页：有 next_token 就继续翻，直到取完。

要拉的数据（日期范围：截止日期往前 62 天，含截止日。月环比要 60 天，多拉 2 天是为了截止日业务数据还没回传时，主代理能把锚点往前挪）
1. 店铺 sid：help 搜 "店铺"（get_my_sids；广告 profile_id 用 ad_auth_shops；amazon_sc_seller_list 可能没权限），按站点和店铺名匹配；同站点多个店铺且无法确定 → 停下，把店铺列表返回给主代理，不要猜。
2. 销售与流量（按天）：help 搜 "产品表现"（query_product_performance_asin_lists），search_field=asin（父体用 parent_asin），date_view_type=day，currency_code 用站点本币。取每天的：总订单、总销量、总销售额、Sessions/页面浏览、广告花费（如有）、价格、评分、库存（如有）。
   - **去年同期（年同比用）**：同一个工具再拉一段 60 天，日期 = 今年的范围整体往前推 **364 天**（按星期对齐），写成 `daily_ly.csv`，列和 daily.csv 一样（budget、organic_impressions 留空）。去年这时还没上架、或有些天没数据，有几天写几天，README 写明；完全没有就不建这个文件。
3. 广告活动日报：help 搜 "广告活动报告"（ad_campaign_report，可按 asin 和单日 report_date 筛，SP/SB/SD 都在里面）。筛出投放该 ASIN 的活动（help 搜 "广告商品报告"，ad_campaign_product_report 确认活动里含该 ASIN）。按天汇总：曝光、点击、花费、广告订单、广告销售额；活动每日预算求和得 budget。**领星只返回当前预算、没有历史预算时，budget 只填截止日那一行，其他天留空**，不要用当前预算回填历史（会算出假的预算变化），README 写明。
4. 搜索词报告：help 搜 "搜索词报告"（ad_campaign_search_term_report，可按 asin 筛，SP+SB 都在里面），分两期：
   - 本期 = 截止日往前 7 天
   - 上期 = 再往前 7 天
   只保留上面确认过的活动。
5. 广告位报告（第⑥层用）：help 搜 "广告位报告"（SP 用 get_sp_campaign_placement_report，"全部位置"那个，不是"企业购"），只保留上面确认过的活动，按本期（截止日往前 7 天）和上期（再往前 7 天）各汇总一次。没有这个接口就跳过，记为缺失。
6. 广告操作日志：help 搜 "操作日志"，和 daily.csv 同一日期范围（月环比要找下滑起点，可能在 30 天以前），相关活动的竞价/预算/状态/否词变更。
   - 优先用字段级日志（ad_operation_log_standard，能看出改了竞价、预算、状态还是否词）。
   - 字段级的已下线时，用运营日志（analytics_log_list_v2，只有日期 + 对象 + 新增/修改）：field 填"新增"/"修改"，old_value/new_value 留空，README 写明"只有按天汇总"。
   - 再看输出目录的上一级 `<skill目录>/data/ad-data/` 下同一 ASIN 以前拉过的 op_log.csv：有字段级记录、日期又在本次范围里的，合并进来，operator 后面加"（来自 <文件夹名>）"。
7. 自然曝光（可选）：help 搜 "搜索查询绩效" / "SQP" / "Search Query Performance"；有则按天或按周取该 ASIN 的总曝光、总点击。没有就跳过，记为缺失。

输出文件（UTF-8 带 BOM 的 CSV，列名必须完全一致，金额统一站点本币，缺失值留空）
- daily.csv：date,impressions,clicks,spend,ad_orders,ad_sales,budget,total_orders,total_sales,sessions,organic_impressions,price,rating,inventory
  （按天一行；impressions/clicks/spend/ad_orders/ad_sales 用**该 ASIN 自己的**广告数据（产品表现/产品广告报告，SP+SB+SD 合计），不要用活动合计——活动里可能还有别的 ASIN；organic_impressions = SQP 总曝光 − 广告曝光，无 SQP 则留空；截止日的 sessions/总订单等领星还没回传就留空，不要填 0，并在 README.txt 写明）
- daily_ly.csv：去年同期 60 天（今年日期 − 364 天），列同 daily.csv；trend 用它算 7 天 / 30 天年同比
- variant_ads.csv：asin,impressions,clicks,spend,orders,sales（近 7 天，上面确认过的活动里每个广告 ASIN 一行，用 ad_sp_product_ad_reports 等产品广告报告汇总；用于核对"只投了这个 ASIN"）
- campaigns_daily.csv：date,campaign_id,campaign,ad_type,impressions,clicks,spend,orders,sales,budget（活动级合计；活动常改名、名字里带日期，同一活动按 campaign_id 认，campaign 填截止日的名字；budget 规则同 daily.csv）
- st_curr.csv / st_prev.csv：campaign,ad_group,match_type,targeting,search_term,impressions,clicks,spend,orders,sales
- op_log.csv：time,campaign_id,campaign,object,field,old_value,new_value,operator
- placement.csv：period,campaign,placement,impressions,clicks,spend,orders,sales（period 填 curr / prev；placement 填 首页顶部 / 其余位置 / 商品页）
- README.txt：每个文件的数据来源 toolId、日期范围、行数、缺失项和原因

原始返回（JSON 等）只是中间文件：放在输出目录下的 `_raw/` 里解析，**CSV 生成并核对完行数后，删除整个 `_raw/`**。数据目录在 skill 的 `data/` 下，原始文件留着会让 skill 文件夹越来越大（一次可达几十 MB），插件更新时也会被整个复制。只有 CSV、README.txt、报告和归因文件需要保留。

输出目录写不进去（被权限或保护机制拦截）时，停下来，回复第一行写明哪个路径写不进去、报错原文，不要改写到其他目录。

最后只回复（不要贴数据内容）：
1. 输出目录和文件列表（每个文件行数）
2. 缺失或不完整的数据及原因
3. 一句话说明数据覆盖的日期范围
4. 实际用到的 toolId，和上面括号里参考的不一致时标出来
```

---

## 备注（给主代理）

- 领星 toolId 会随版本变化，模板里括号中的是 2026-11 实测可用的 ID；子代理按中文关键词找。子代理回报的 toolId 和括号里不一致时，主代理更新本文件。
- 如果用户上传了报表而不是用领星：主代理自己（或子代理）把报表转成上面同样的列名和文件名即可，后续脚本通用。
