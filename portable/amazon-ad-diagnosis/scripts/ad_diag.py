"""亚马逊广告诊断辅助脚本。

子命令:
  trend   daily.csv 日/周/月多周期对比（流量×CVR + 广告 + 自然），诊断框架第②③层判定，
          危险信号，以及第一个异常的变量
  terms   两期搜索词报告对比，判断词结构是否变化，列出新进花费词
  filter  搜索词/关键词报告组合筛选（烧钱不出单 / ACOS 超标 / 低效高曝光 / 优质词）
  harvest 关键词机会 K1：已出单、ACOS 达标、还没单独精准投放的搜索词（收割候选 + 建议竞价 + 来源活动否定）

daily.csv 列名（子代理按此输出）:
  date,impressions,clicks,spend,ad_orders,ad_sales,budget,total_orders,total_sales,
  sessions,organic_impressions,price,rating,inventory
搜索词报告支持 CSV / XLSX，中英文后台表头自动识别。
"""
import argparse
import math
import re
import sys

import pandas as pd

# ---------------------------------------------------------------- 通用读取

COLUMN_PATTERNS = {
    "campaign": ["campaignname", "campaign", "广告活动名称", "广告活动"],
    "ad_group": ["adgroupname", "adgroup", "广告组名称", "广告组"],
    "match_type": ["matchtype", "匹配类型"],
    "search_term": ["customersearchterm", "searchterm", "客户搜索词", "搜索词"],
    "targeting": ["targeting", "keywordtext", "keyword", "投放", "关键词"],
    "impressions": ["impressions", "展示量", "曝光量", "展示次数", "曝光"],
    "clicks": ["clicks", "点击量", "点击次数", "点击"],
    "spend": ["spend", "cost", "花费", "支出"],
    "sales": ["7daytotalsales", "14daytotalsales", "totalsales", "sales", "7天总销售额", "14天总销售额", "总销售额", "销售额"],
    "orders": ["7daytotalorders", "14daytotalorders", "totalorders", "orders", "7天总订单数", "14天总订单数", "总订单数", "订单数", "订单"],
}
NUMERIC = ["impressions", "clicks", "spend", "sales", "orders"]


def _norm(s):
    return re.sub(r"[\s_\-()（）#]", "", str(s)).lower()


def read_any(path):
    if str(path).lower().endswith((".xlsx", ".xls")):
        return pd.read_excel(path)
    for enc in ("utf-8-sig", "gbk", "latin-1"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
    sys.exit(f"无法读取 {path}")


def to_num(s):
    return pd.to_numeric(s.astype(str).str.replace(r"[^\d.\-]", "", regex=True), errors="coerce")


def load_report(path):
    df = read_any(path)
    mapping, used = {}, set()
    normed = {c: _norm(c) for c in df.columns}
    for field, pats in COLUMN_PATTERNS.items():
        for p in pats:
            hit = next((c for c, n in normed.items() if c not in used and p in n
                        and not (field == "orders" and "units" in n)
                        and not (field == "sales" and ("acos" in n or "roas" in n))
                        and not (field == "targeting" and "type" in n)
                        and not (field == "campaign" and ("id" == n[-2:] or "type" in n))), None)
            if hit:
                mapping[hit] = field
                used.add(hit)
                break
    df = df.rename(columns=mapping)
    missing = [f for f in ["clicks", "spend", "orders"] if f not in df.columns]
    if missing:
        sys.exit(f"[{path}] 找不到必需列 {missing}；现有列: {list(df.columns)}")
    for f in NUMERIC:
        df[f] = to_num(df[f]).fillna(0) if f in df.columns else 0.0
    return df


def rate_arg(v):
    """55% / 55 / 0.55 都当作 55%"""
    t = str(v).strip()
    try:
        x = float(t.rstrip("%"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"无法识别的比例: {v}（写 55%、55 或 0.55）")
    x = x / 100 if (t.endswith("%") or x > 1) else x
    if not 0 < x < 5:
        raise argparse.ArgumentTypeError(f"比例超出范围: {v}")
    return x


def div(a, b):
    return a / b if b else math.nan


def pct(a, b):
    return (b - a) / a if a and not math.isnan(a) else math.nan


def fmt(v, kind):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "-"
    if kind == "pct":
        return f"{v:.1%}"
    if kind == "chg":
        return f"{v:+.1%}"
    if kind == "money":
        return f"{v:,.2f}"
    return f"{v:,.0f}"


# ---------------------------------------------------------------- trend

# (名称, 格式, 是否订单类, 上升是好事?)
TREND_METRICS = [
    ("日均流量(Sessions)", "int", False, True), ("整体CVR", "pct", True, True),
    ("曝光", "int", False, True), ("预算", "money", False, None), ("预算使用率", "pct", False, None),
    ("花费", "money", False, None), ("点击", "int", False, True), ("CTR", "pct", False, True),
    ("CPC", "money", False, False), ("CPM", "money", False, False),
    ("广告订单", "int", True, True), ("广告CVR", "pct", True, True),
    ("ACOS", "pct", True, False), ("TACOS", "pct", True, False),
    ("总订单", "int", True, True), ("自然订单", "int", True, True), ("广告订单占比", "pct", True, None),
    ("自然曝光", "int", False, True), ("自然点击", "int", False, True),
    ("自然点击率", "pct", False, True), ("自然转化率", "pct", True, True),
]
THRESH = {"日环比": 0.20, "上周同日": 0.20, "周环比": 0.15, "月环比": 0.10, "7天同比": 0.15, "30天同比": 0.10, "去年周环比": 0.15, "去年月环比": 0.10}
YOY_SHIFT = 364  # 年同比按 52 周对齐（星期几一致）
ENV_PERIODS = ("日环比", "周环比", "月环比", "去年月环比", "30天同比")  # 日 / 周 / 月 / 去年同期月环比 / 年同比
SEASONAL_PP = 0.10  # 今年月环比比去年同期月环比多变差不到 10 个百分点 → 算季节性


# 业务报表类列（领星常晚 1-2 天回传），某几天可能为空
LAGGING = ["total_orders", "total_sales", "sessions", "organic_impressions"]


def period_metrics(d):
    def some(c):
        return c in d and d[c].notna().any()

    def full(c):  # 本期每天都有值
        return c in d and len(d) > 0 and d[c].notna().all()

    def ssum(c, mask=None):
        if c not in d:
            return 0.0
        x = d[c] if mask is None else d.loc[mask, c]
        return float(x.fillna(0).sum())

    def mask(*cols):  # 这些列同时有值的天
        m = pd.Series(True, index=d.index)
        for c in cols:
            m &= d[c].notna() if c in d else False
        return m

    imp, clk, sp, ao, asl = (ssum(c) for c in ["impressions", "clicks", "spend", "ad_orders", "ad_sales"])
    # 领星常只给当前预算（只填截止日）：整期每天都有预算才算多日周期的预算和使用率
    bud = ssum("budget") if full("budget") else math.nan
    # 总量：整期每天都有数据才给出，否则不可比（显示 "-"）
    to = ssum("total_orders") if full("total_orders") else math.nan
    org_o = to - ao if full("total_orders") else math.nan
    org_c = ssum("sessions") - clk if full("sessions") else math.nan
    org_i = ssum("organic_impressions") if full("organic_impressions") else math.nan
    # 比率：只用分子分母都有数据的天计算，缺几天也可比
    m_ts, m_to = mask("total_sales"), mask("total_orders")
    m_cvr, m_ctr = mask("sessions", "total_orders"), mask("sessions", "organic_impressions")
    cvr_c = ssum("sessions", m_cvr) - ssum("clicks", m_cvr)
    ctr_c = ssum("sessions", m_ctr) - ssum("clicks", m_ctr)
    # 流量和整体 CVR 用有 Sessions 的天算日均 / 比率，缺一两天也可比
    m_s = mask("sessions")
    day_s = float(d.loc[m_s, "sessions"].mean()) if m_s.any() else math.nan
    day_nc = float((d.loc[m_s, "sessions"] - d.loc[m_s, "clicks"].fillna(0)).mean()) if m_s.any() else math.nan
    cvr_all = div(ssum("total_orders", m_cvr), ssum("sessions", m_cvr)) if m_cvr.any() else math.nan
    return {
        "日均流量(Sessions)": day_s, "整体CVR": cvr_all, "_日均自然点击": day_nc,
        "曝光": imp, "预算": bud, "预算使用率": div(sp, bud) if not math.isnan(bud) else math.nan,
        "花费": sp, "点击": clk, "CTR": div(clk, imp), "CPC": div(sp, clk), "CPM": div(sp, imp) * 1000 if imp else math.nan,
        "广告订单": ao, "广告CVR": div(ao, clk), "ACOS": div(sp, asl),
        "TACOS": div(ssum("spend", m_ts), ssum("total_sales", m_ts)) if some("total_sales") else math.nan,
        "总订单": to, "自然订单": org_o,
        "广告订单占比": div(ssum("ad_orders", m_to), ssum("total_orders", m_to)) if some("total_orders") else math.nan,
        "自然曝光": org_i, "自然点击": org_c,
        "自然点击率": div(ctr_c, ssum("organic_impressions", m_ctr)) if m_ctr.any() else math.nan,
        "自然转化率": div(ssum("total_orders", m_cvr) - ssum("ad_orders", m_cvr), cvr_c)
        if m_cvr.any() and cvr_c > 0 else math.nan,
    }


# 诊断框架"找第一个异常变量"：(名称, 计算函数, 不利方向 -1下降/+1上升/0任一方向, 阈值, 需要的列)
ANOMALY = [
    ("日均流量(Sessions)", lambda w: w["sessions"].mean(), -1, 0.15, ["sessions"]),
    ("整体CVR", lambda w: div(w["total_orders"].sum(), w["sessions"].sum()), -1, 0.15, ["total_orders", "sessions"]),
    ("总订单", lambda w: w["total_orders"].mean(), -1, 0.15, ["total_orders"]),
    ("自然订单", lambda w: (w["total_orders"] - w["ad_orders"]).mean(), -1, 0.15, ["total_orders", "ad_orders"]),
    ("广告订单", lambda w: w["ad_orders"].mean(), -1, 0.15, ["ad_orders"]),
    ("广告曝光", lambda w: w["impressions"].mean(), -1, 0.15, ["impressions"]),
    ("广告点击", lambda w: w["clicks"].mean(), -1, 0.15, ["clicks"]),
    ("CPC", lambda w: div(w["spend"].sum(), w["clicks"].sum()), 1, 0.15, ["spend", "clicks"]),
    ("价格", lambda w: w["price"].mean(), 0, 0.05, ["price"]),
    ("评分", lambda w: w["rating"].mean(), -1, 0.02, ["rating"]),
    ("库存", lambda w: w["inventory"].mean(), -1, 0.30, ["inventory"]),
]


def promo_days(win):
    """疑似大促 / 异常日：售价比中位数低 10% 以上，或 Sessions 达到中位数 2 倍以上"""
    out = set()
    for col, cond in (("price", lambda x, m: x <= m * 0.9), ("sessions", lambda x, m: x >= m * 2)):
        if col in win and win[col].notna().sum() >= 10:
            med = win[col].median()
            out |= set(win.loc[cond(win[col], med), "date"])
    return out


def first_anomaly(df, anchor, promo=()):
    """近 30 天里，各变量 7 天滚动均值第一次持续（连续 3 天）偏离基准（D-59~D-30 日均）的时间。基准去掉大促日"""
    D = pd.Timedelta(days=1)
    s = df.set_index("date").sort_index()
    base = s.loc[anchor - 59 * D: anchor - 30 * D]
    base = base[~base.index.isin(list(promo))]
    print("\n—— 第一个异常的变量（7 天滚动均值 vs 基准 D−59~D−30，连续 3 天超阈值才算）——")
    if len(base) < 20:
        print("基准期数据不足 20 天，无法判断")
        return
    rows = []
    for name, f, bad, th, cols in ANOMALY:
        if any(c not in s.columns or s[c].notna().sum() == 0 for c in cols):
            continue
        b = f(base.dropna(subset=cols))
        if b is None or (isinstance(b, float) and math.isnan(b)) or b == 0:
            continue
        flags, days = [], []
        for k in range(30):
            d = anchor - (29 - k) * D
            w = s.loc[d - 6 * D: d].dropna(subset=cols)
            days.append(d)
            if len(w) < 5:
                flags.append(None)
                continue
            dev = (f(w) - b) / abs(b)
            hit = dev < -th if bad < 0 else (dev > th if bad > 0 else abs(dev) > th)
            flags.append((hit, dev))
        first = next((i for i in range(len(flags) - 2)
                      if all(flags[j] and flags[j][0] for j in (i, i + 1, i + 2))), None)
        if first is not None:
            last = next((fl for fl in reversed(flags) if fl), None)
            rows.append((days[first], name, flags[first][1], last[1] if last else math.nan))
    if not rows:
        print("近 30 天没有变量持续偏离基准")
        return
    rows.sort(key=lambda r: r[0])
    print("| 变量 | 首次持续偏离（7 天窗口） | 当时偏离 | 截止日偏离 |")
    print("|---|---|---|---|")
    for d, name, dev0, devn in rows:
        print(f"| {name} | {(d - 6 * D).date()} ~ {d.date()} | {fmt(dev0, 'chg')} | {fmt(devn, 'chg')} |")
    first_d = rows[0][0]
    firsts = [r[1] for r in rows if r[0] == first_d]
    print(f"→ 最先异常：{'、'.join(firsts)}（变化发生在 {(first_d - 6 * D).date()} ~ {first_d.date()} 之间）。"
          "按诊断框架从它所在的层开始查，并到 op_log 里找这段时间的操作。")
    print("  注意：基准期本身已经在下滑时，真实起点可能更早；阈值：订单/流量/点击 ±15%，价格 ±5%，评分 −2%，库存 −30%")
    return first_d - 6 * D, firsts


# ---------------------------------------------------------------- 跨周期一致性矩阵

MATRIX_METRICS = ["总订单", "日均流量(Sessions)", "整体CVR", "自然订单", "广告订单", "曝光", "点击", "CTR",
                  "广告CVR", "CPC", "ACOS", "TACOS"]


def _worse(f, up_good):
    """1 = 朝不利方向，-1 = 朝有利方向，0 = 没超阈值"""
    if not f:
        return 0
    return 1 if (f > 0) != up_good else -1


def interpret(d, w, mo, y, mo_chg, lymo_chg, up_good):
    """季节性看"今年月环比 vs 去年同期月环比"；年同比只说明长期水平。d/w/mo/y：1 = 朝不利方向，-1 = 有利，0 = 没超阈值"""
    sign = 1 if up_good else -1
    if mo == 1:
        if math.isnan(lymo_chg):
            s = "月度变差；缺去年同期月环比，分不清季节性还是今年的问题"
        else:
            excess = (lymo_chg - mo_chg) * sign  # >0：今年比去年同期多变差
            pair = f"今年 {mo_chg:+.1%}，去年同期 {lymo_chg:+.1%}"
            if excess < SEASONAL_PP:
                s = f"偏季节性：去年同期也这样变（{pair}）"
            else:
                s = f"今年真的变差：比去年同期多变差 {excess * 100:.1f}pp（{pair}）"
    elif w == 1:
        s = "近期才开始变差：找最近一周的操作 / 竞品动作"
    elif d == 1:
        s = "单日波动：观察，不下结论"
    elif mo == -1 or w == -1:
        s = "在改善"
    else:
        s = "稳定"
    if mo == 1 and w == -1:
        s += "；本周已回升，但月度下滑仍是主线"
    if mo == -1 and w == 1 and not s.startswith("近期"):
        s += "；本周回落，要盯"
    if y == 1:
        s += "；和去年同期比整体也变差（长期偏弱）"
    elif y == -1 and mo == 1:
        s += "；整体水平仍高于去年同期"
    return s


def cross_period_matrix(flag_map, has_ly):
    arrow = {1: "↑", -1: "↓", 0: "→"}
    print("\n—— 跨周期一致性（日 / 周 / 月 / 年同比，箭头是指标本身的方向，⚠ = 朝不利方向）——")
    print("| 指标 | 日 | 周 | 月 | 去年同期月环比 | 年同比(30天) | 差异解读 |")
    print("|---|---|---|---|---|---|---|")
    summary = None
    for m in MATRIX_METRICS:
        if m not in flag_map:
            continue
        flags, chg, up_good = flag_map[m]
        if up_good is None or all(math.isnan(chg[p]) for p in ENV_PERIODS):
            continue
        cells, worse = [], {}
        for p in ENV_PERIODS:
            if math.isnan(chg[p]):
                cells.append("-")
                worse[p] = None
                continue
            f = flags[p]
            wv = _worse(f, up_good)
            worse[p] = wv
            cells.append(f"{arrow[f]}{' ⚠' if wv == 1 else ''} {fmt(chg[p], 'chg')}")
        text = interpret(worse["日环比"] or 0, worse["周环比"] or 0, worse["月环比"] or 0,
                         worse["30天同比"] or 0, chg["月环比"], chg["去年月环比"], up_good)
        if m == "总订单":
            summary = text
        print(f"| {m} | " + " | ".join(cells) + f" | {text} |")
    if not has_ly:
        print("（没有 daily_ly.csv：去年同期列为 '-'。季节性只能靠第①层外部数据判断）")
    print("说明：季节性看\"今年月环比 vs 去年同期月环比\"（去年这个时候是不是也这样变）；年同比只说明整体水平比去年高还是低，"
          "产品在增长期时年同比会一直为正，不能拿来判断季节性。")
    if summary:
        print(f"→ 总订单的跨周期结论：{summary}。报告第二部分要写这一行，并说明其他指标和它一致还是矛盾。")


# 第①层（外部）先做：按总订单的判定选主周期
PRIMARY_PERIOD = [
    ("持续下降", "月", "周", "大盘这个月是不是也在跌、跌了多少"),
    ("周升月降", "月", "周", "月度下滑是不是大盘带的；本周回升是大盘回暖还是自己调整的结果"),
    ("周降月升", "周", "月", "这周大盘有没有突然下跌（节后、竞品大促）"),
    ("近一周下降", "周", "月", "这周大盘有没有突然下跌（节后、竞品大促）"),
    ("月度下降", "月", "周", "是不是季节性 / 缓慢的下行趋势"),
    ("单日波动", "不深挖", "周、月", "只确认周、月大盘是否稳定，省西柚 credits"),
]


def external_inputs(df, anchor, verdict, chg, start, promo=()):
    D = pd.Timedelta(days=1)
    print("\n—— 第①层 市场需求（外部）输入：按 SOP 先做外部 ——")
    print(f"自身变化率 S（总订单）：日 {fmt(chg.get('日环比', math.nan), 'chg')}，"
          f"周 {fmt(chg.get('周环比', math.nan), 'chg')}，月 {fmt(chg.get('月环比', math.nan), 'chg')}，"
          f"去年同期月环比 {fmt(chg.get('去年月环比', math.nan), 'chg')}，"
          f"年同比(30天) {fmt(chg.get('30天同比', math.nan), 'chg')}；trend 判定：{verdict}")
    mv, lv = chg.get("月环比", math.nan), chg.get("去年月环比", math.nan)
    if not math.isnan(mv) and mv < -0.10:
        if math.isnan(lv):
            print("季节性线索：缺去年同期数据，外部要用西柚 / ABA 的去年同期数据判断季节性")
        elif mv - lv > -SEASONAL_PP:
            print(f"季节性线索：去年同期月环比 {lv:+.1%}，今年 {mv:+.1%} → 本月下滑偏季节性，外部核对去年同期市场是否也这样跌")
        else:
            print(f"季节性线索：去年同期月环比 {lv:+.1%}，今年 {mv:+.1%}，多降 {(lv - mv) * 100:.1f}pp → 超出季节性的部分是今年的问题，"
                  "外部重点找今年的变化（竞品、价格、搜索量）")
    hit = next((r for r in PRIMARY_PERIOD if verdict.startswith(r[0])), None)
    if hit:
        print(f"主周期：{hit[1]}（辅助：{hit[2]}）→ 外部要回答：{hit[3]}")
    elif math.isnan(chg.get("月环比", math.nan)) and math.isnan(chg.get("周环比", math.nan)):
        print("主周期：无法确定——数据天数不足，周环比和月环比都算不出来。外部只能做背景确认，报告写明数据不足")
    elif math.isnan(chg.get("月环比", math.nan)):
        print("主周期：周（数据不足 60 天，月环比算不出来；报告写明）")
    else:
        print("主周期：总订单没有下降，外部只做背景确认（周、月各一行），不深挖")
    if start is not None:
        s = df.set_index("date").sort_index()
        pre_a, pre_b = start - 14 * D, start - D
        post_b = min(start + 13 * D, anchor)
        pre = s.loc[pre_a:pre_b, "total_orders"] if "total_orders" in s else pd.Series(dtype=float)
        dropped = [d for d in pre.index if d in set(promo)]
        pre = pre[~pre.index.isin(dropped)]
        post = s.loc[start:post_b, "total_orders"] if "total_orders" in s else pd.Series(dtype=float)
        sc = pct(pre.mean(), post.mean()) if len(pre) and len(post) else math.nan
        print(f"异常起点：{start.date()}。起点前后对比窗口：{pre_a.date()}~{pre_b.date()} vs {start.date()}~{post_b.date()}，"
              f"自身日均总订单 {fmt(sc, 'chg')}"
              + (f"（起点前窗口已去掉大促/异常日 {', '.join(str(d.date()) for d in dropped)}）" if dropped else ""))
        print("→ 外部先在这两个窗口比较市场（核心词搜索量）和竞品（BSR / 价格 / Deal），再按主周期做日历周期对比。"
              "类目市场规模一般只有 30 天 / 月粒度，周级别用核心词搜索量和竞品判断。")
    else:
        print("没有找到异常起点：只做日历周期（主周期）对比")


def anchor_gap_hint(df, anchor):
    """锚点日缺业务数据时的建议：只有往前挪一天后月对比仍完整，才建议挪。"""
    first = df["date"].min()
    if anchor - pd.Timedelta(days=60) >= first:
        return "；锚点日缺数据：数据够长，可以 --date 往前挪一天（报告写明实际用的截止日）"
    days = (anchor - first).days + 1
    return (f"；锚点日缺数据，但数据只有 {days} 天，往前挪会丢掉月环比 —— **不要挪**，"
            "保持当前 --date，报告注明锚点日这些字段缺失")


def cmd_trend(a):
    df = read_any(a.file)
    df.columns = [str(c).strip().lower() for c in df.columns]
    if "date" not in df.columns:
        sys.exit("daily.csv 缺少 date 列")
    df["date"] = pd.to_datetime(df["date"])
    for c in df.columns:
        if c != "date":
            df[c] = to_num(df[c])
    df = df.groupby("date").sum(min_count=1).reset_index()
    if df.empty:
        sys.exit(f"{a.file} 里没有数据行，无法分析。先确认拉数据是否成功。")
    anchor = pd.Timestamp(a.date) if a.date else df["date"].max()
    D = pd.Timedelta(days=1)

    def rng(start, end, src=None):
        src = df if src is None else src
        sub = src[(src["date"] >= start) & (src["date"] <= end)]
        days = (end - start).days + 1
        return sub if len(sub) == days else None  # 天数不全视为不可用

    # 年同比：去年同期数据（daily_ly.csv，和 daily.csv 同列），日期往后挪 364 天对齐到今年
    from pathlib import Path
    ly_path = a.ly or str(Path(a.file).with_name("daily_ly.csv"))
    ly = None
    if Path(ly_path).exists():
        ly = read_any(ly_path)
        ly.columns = [str(c).strip().lower() for c in ly.columns]
        ly["date"] = pd.to_datetime(ly["date"])
        for c in ly.columns:
            if c != "date":
                ly[c] = to_num(ly[c])
        ly = ly.groupby("date").sum(min_count=1).reset_index()
        ly["date"] = ly["date"] + pd.Timedelta(days=YOY_SHIFT)

    def rng_ly(start, end):
        return None if ly is None else rng(start, end, ly)

    periods = {
        "日环比": (rng(anchor, anchor), rng(anchor - D, anchor - D)),
        "上周同日": (rng(anchor, anchor), rng(anchor - 7 * D, anchor - 7 * D)),
        "周环比": (rng(anchor - 6 * D, anchor), rng(anchor - 13 * D, anchor - 7 * D)),
        "月环比": (rng(anchor - 29 * D, anchor), rng(anchor - 59 * D, anchor - 30 * D)),
        "7天同比": (rng(anchor - 6 * D, anchor), rng_ly(anchor - 6 * D, anchor)),
        "30天同比": (rng(anchor - 29 * D, anchor), rng_ly(anchor - 29 * D, anchor)),
        # 去年同期自己的环比：判断季节性（去年这个时候是不是也这样变）
        "去年周环比": (rng_ly(anchor - 6 * D, anchor), rng_ly(anchor - 13 * D, anchor - 7 * D)),
        "去年月环比": (rng_ly(anchor - 29 * D, anchor), rng_ly(anchor - 59 * D, anchor - 30 * D)),
    }
    res = {}
    for name, (cur, prev) in periods.items():
        if cur is None or prev is None:
            res[name] = None
        else:
            res[name] = (period_metrics(cur), period_metrics(prev))

    print(f"锚点日期: {anchor.date()}   数据范围: {df['date'].min().date()} ~ {df['date'].max().date()}")
    missing = [n for n, v in res.items() if v is None and "同比" not in n and not n.startswith("去年")]
    if missing:
        print(f"数据天数不足，无法计算: {', '.join(missing)}")
    if ly is None:
        print(f"⚠ 没有去年同期数据（{Path(ly_path).name}），年同比显示 '-'，分不清季节性和今年的问题；新品不满一年属正常")
    elif res["30天同比"] is None or res["7天同比"] is None or res["去年月环比"] is None:
        print("⚠ 去年同期数据天数不全，部分年同比显示 '-'（去年这时可能还没上架或断货）")
    win = df[(df["date"] >= anchor - 59 * D) & (df["date"] <= anchor)]
    for c in LAGGING:
        if c in win and win[c].notna().any() and win[c].isna().any():
            gaps = [str(x.date()) for x in win.loc[win[c].isna(), "date"]]
            print(f"⚠ {c} 有 {len(gaps)} 天为空: {', '.join(gaps[:5])}{' …' if len(gaps) > 5 else ''}"
                  f" —— 含这些天的周期，相关总量显示 '-'，比率只用有数据的天计算"
                  + (anchor_gap_hint(df, anchor) if str(anchor.date()) in gaps else ""))
    if "budget" in win and win["budget"].notna().any() and win["budget"].isna().any():
        print(f"⚠ budget 只有 {int(win['budget'].notna().sum())} 天有值（领星通常只给当前预算）"
              " —— 多日周期的预算和预算使用率显示 '-'，只看今日")
    promo = promo_days(win)
    if promo:
        ds = sorted(promo)
        print(f"⚠ 疑似大促/异常日 {len(ds)} 天: {', '.join(str(x.date()) for x in ds[:8])}{' …' if len(ds) > 8 else ''}"
              " —— 售价比中位数低 10% 以上或 Sessions ≥ 中位数 2 倍。含这些天的周期变化会被放大，报告要写明；"
              "第一个异常变量的基准已去掉这些天")
        cur, prev = periods["月环比"]
        if cur is not None and prev is not None:
            c2, p2 = cur[~cur["date"].isin(ds)], prev[~prev["date"].isin(ds)]
            parts = [f"{lab} {fmt(pct(p2[col].mean(), c2[col].mean()), 'chg')}"
                     for lab, col in (("日均流量(Sessions)", "sessions"), ("日均总订单", "total_orders"))
                     if col in df]
            print("  去掉这些天后的月环比：" + "，".join(parts))
    cur_day = res["日环比"][0] if res["日环比"] else None
    cur_wk = res["周环比"][0] if res["周环比"] else None
    small = cur_wk is not None and not math.isnan(cur_wk["总订单"]) and cur_wk["总订单"] < 30

    hdr = ["指标", "今日", "日环比", "上周同日", "近7天", "周环比", "近30天", "月环比", "7天同比", "30天同比", "判定"]
    flag_map = {}
    rows = []
    for m, kind, is_order, up_good in TREND_METRICS:
        chg = {}
        for p in THRESH:
            chg[p] = pct(res[p][1][m], res[p][0][m]) if res[p] else math.nan
        flags = {}
        for p, t in THRESH.items():
            t2 = t * 2 if (is_order and small) else t
            v = chg[p]
            flags[p] = 0 if math.isnan(v) or abs(v) < t2 else (1 if v > 0 else -1)
        w, mo, d = flags["周环比"], flags["月环比"], flags["日环比"]
        if w and mo and w == mo:
            verdict = "持续上升" if w > 0 else "持续下降"
        elif w and mo:
            # 周、月方向相反：短期反弹/回落不能掩盖月度趋势，两个都要写进结论
            verdict = "周升月降（月度仍下降）" if w > 0 else "周降月升（近期回落）"
        elif w:
            verdict = "近一周上升" if w > 0 else "近一周下降"
        elif mo:
            verdict = "月度上升" if mo > 0 else "月度下降"
        elif d:
            verdict = "单日波动，观察"
        else:
            verdict = "持平"
        if verdict not in ("持平",) and up_good is not None:
            if w and mo and w != mo:
                # 方向相反时任一周期朝不利方向都要提示
                verdict += " ⚠" if ((w > 0) != up_good or (mo > 0) != up_good) else ""
            else:
                direction = w or mo or d
                verdict += " ⚠" if (direction > 0) != up_good else ""
        if all(math.isnan(chg[p]) for p in THRESH):  # 一个周期都比不了（如只有当前预算）
            verdict = "缺数据"
        if m == "总订单":
            orders_verdict, orders_chg = verdict, dict(chg)
        flag_map[m] = (flags, chg, up_good)
        rows.append([
            m,
            fmt(cur_day[m], kind) if cur_day else "-",
            fmt(chg["日环比"], "chg"), fmt(chg["上周同日"], "chg"),
            fmt(cur_wk[m], kind) if cur_wk else "-", fmt(chg["周环比"], "chg"),
            fmt(res["月环比"][0][m], kind) if res["月环比"] else "-", fmt(chg["月环比"], "chg"),
            fmt(chg["7天同比"], "chg"), fmt(chg["30天同比"], "chg"),
            verdict,
        ])
    print("\n| " + " | ".join(hdr) + " |")
    print("|" + "---|" * len(hdr))
    for r in rows:
        print("| " + " | ".join(r) + " |")
    print("\n阈值: 日/上周同日 ±20%，周 / 7天同比 ±15%，月 / 30天同比 ±10%；⚠ = 朝不利方向变化；"
          "同比 = 去年同期（往前 364 天，星期对齐）"
          + ("；本周订单 <30，订单类阈值已翻倍" if small else ""))

    cross_period_matrix(flag_map, ly is not None)

    # 广告 vs 自然：周、月各判一次，方向不一致时明确提示
    ad_org = {}
    for p, label in (("周环比", "周"), ("月环比", "月")):
        if not res[p]:
            print(f"\n[{label}] 数据天数不足，无法判断广告 vs 自然")
            continue
        cur, prev = res[p]
        ad, org = pct(prev["广告订单"], cur["广告订单"]), pct(prev["自然订单"], cur["自然订单"])
        t = THRESH[p]
        print(f"\n[{label}] 广告订单 {fmt(ad, 'chg')}，自然订单 {fmt(org, 'chg')} → ", end="")
        if math.isnan(ad) or math.isnan(org):
            msg = "数据不全（总订单缺天或为 0），无法判断"
        elif ad < -t and org < -t:
            msg = "一起降：优先查 Listing/库存/Buy Box/市场，以及广告大幅收缩是否拖累自然"
        elif ad > t and org > t:
            msg = "一起涨：广告带动自然，确认是否因加预算/新开活动"
        elif ad < -t:
            msg = "只有广告降：广告本身问题，看曝光→CTR→CVR 哪层先掉"
        elif org < -t:
            msg = "自然降、广告稳：自然排名/Listing 问题"
        elif ad < -t / 2 and org > t:
            msg = "广告降、自然涨：可能互相替代，看 TACOS"
        else:
            msg = "无明显异常"
        print(msg)
        ad_org[label] = msg
    if len(ad_org) == 2 and ad_org["周"] != ad_org["月"]:
        print("⚠ 周和月的结论不一致：报告必须同时写出两个周期，不能只用本周结论代替月度趋势；"
              "月度下滑要对照 op_log 找起点日期")

    # 诊断框架：第②层（流量 × CVR）、第③层（自然 vs 广告）、危险信号
    print("\n—— 诊断框架分层判定（规则见 references/diagnosis-framework.md）——")
    for p, label in (("周环比", "周"), ("月环比", "月")):
        if not res[p]:
            print(f"[{label}] 数据天数不足，无法分层判定")
            continue
        cur, prev = res[p]
        t = THRESH[p]

        def ch(m):
            return pct(prev[m], cur[m])

        tr, cv, od = ch("日均流量(Sessions)"), ch("整体CVR"), ch("总订单")
        if math.isnan(tr) or math.isnan(cv):
            l2 = "Sessions 或总订单缺数据，无法拆分流量和转化"
        elif tr < -t and cv < -t:
            l2 = "流量和转化都降 → 双重恶化：先恢复转化（查⑤），再恢复流量"
        elif tr < -t:
            l2 = "流量降、转化稳 → 流量获取问题：查③流量来源、④关键词权重"
        elif cv < -t:
            l2 = "流量稳、转化降 → 转化竞争力问题：查⑤相对竞争力"
        elif not math.isnan(od) and od < -t:
            l2 = "流量和转化单项都没超阈值，但总订单下降：两者小幅叠加，两条线都要看"
        else:
            l2 = "流量和转化都没有明显下降"
        print(f"[{label}·第②层] 日均流量 {fmt(tr, 'chg')}，整体CVR {fmt(cv, 'chg')}，总订单 {fmt(od, 'chg')} → {l2}")

        nat, adc = ch("_日均自然点击"), ch("点击")
        if math.isnan(nat):
            l3 = "Sessions 缺数据，无法拆分自然和广告流量"
        else:
            parts = []
            if nat < -t:
                parts.append("自然流量降 → 查④关键词权重")
            if not math.isnan(adc) and adc < -t:
                parts.append("广告流量降 → 查⑥广告（动作等诊断结果定了再给）")
            l3 = "；".join(parts) or "自然和广告流量都没有明显下降"
        print(f"[{label}·第③层] 日均自然点击(近似) {fmt(nat, 'chg')}，广告点击 {fmt(adc, 'chg')} → {l3}")

        ao_, oo_, sh_ = ch("广告订单"), ch("自然订单"), ch("广告订单占比")
        if not any(math.isnan(x) for x in (ao_, oo_, sh_)) and abs(ao_) < t and oo_ < -t and sh_ > t:
            print(f"[{label}] ⚠ 危险信号：广告订单稳定（{fmt(ao_, 'chg')}），自然订单 {fmt(oo_, 'chg')}，"
                  f"广告订单占比 {fmt(sh_, 'chg')} → 广告在托住表面销量，自然流量能力在下降（偏诊断结果 D）")

    fa = first_anomaly(df, anchor, promo)
    external_inputs(df, anchor, orders_verdict, orders_chg, fa[0] if fa else None, promo)

    if a.out:
        pd.DataFrame(rows, columns=hdr).to_csv(a.out, index=False, encoding="utf-8-sig")
        print(f"已导出: {a.out}")


# ---------------------------------------------------------------- terms

# ---------------------------------------------------------------- SOP 顺序检查

def sop_gate(data_file, force):
    """SOP：广告（第⑥层）最后做。数据目录里还没有 ①（外部）和 ④⑤（内部）的结论文件时，terms / filter / harvest 不运行。"""
    from pathlib import Path
    d = Path(data_file).resolve().parent
    missing = [f for f in ("rootcause_external.md", "rootcause_internal.md") if not (d / f).exists()]
    if not missing:
        return
    msg = (f"⛔ SOP 顺序：第⑥层广告诊断要等第①层（外部）和第④⑤层（内部）写完结论。"
           f"数据目录 {d} 里还没有：{'、'.join(missing)}。\n"
           "先按 SKILL.md 第2步写 rootcause_external.md、第3步写 ②③ 结论、第4步写 rootcause_internal.md，再跑 terms / filter / harvest。")
    if force:
        print(msg.replace("⛔", "⚠") + "\n（已用 --force 跳过检查；报告里要注明第⑥层先于 ④⑤ 做了）\n")
        return
    sys.exit(msg + "\n不要加 --force 绕过：回去补前面的层。核对用户说法用 ad_diag.py structure / oplog，不需要 terms。")


def cmd_terms(a):
    sop_gate(a.curr, a.force)
    p, c = load_report(a.prev), load_report(a.curr)
    key = "search_term" if "search_term" in c.columns else "targeting"
    if key not in c.columns:
        sys.exit("找不到搜索词列")

    def agg(df):
        g = df.groupby(df[key].astype(str).str.strip().str.lower())[NUMERIC].sum()
        g["share"] = g["spend"] / g["spend"].sum() if g["spend"].sum() else 0
        return g.sort_values("spend", ascending=False)

    gp, gc = agg(p), agg(c)
    top_p, top_c = set(gp.head(10).index), set(gc.head(10).index)
    overlap = len(top_p & top_c) / max(len(top_c), 1)
    new_terms = gc[~gc.index.isin(gp.index)]
    new_share = new_terms["spend"].sum() / gc["spend"].sum() if gc["spend"].sum() else 0
    conc_p, conc_c = gp.head(10)["share"].sum(), gc.head(10)["share"].sum()

    signals = []
    if overlap < 0.6:
        signals.append(f"Top10 花费词重合率 {overlap:.0%} (<60%)")
    if new_share > 0.2:
        signals.append(f"新出现词花费占比 {new_share:.0%} (>20%)")
    if abs(conc_c - conc_p) > 0.15:
        signals.append(f"Top10 集中度 {conc_p:.0%} → {conc_c:.0%}")

    print(f"上期词数 {len(gp)}  本期词数 {len(gc)}  Top10 重合率 {overlap:.0%}  新词花费占比 {new_share:.0%}  "
          f"Top10 集中度 {conc_p:.0%} → {conc_c:.0%}")

    if "match_type" in c.columns and "match_type" in p.columns:
        mp = p.groupby(p["match_type"].astype(str).str.upper())["spend"].sum()
        mc = c.groupby(c["match_type"].astype(str).str.upper())["spend"].sum()
        mp, mc = mp / mp.sum(), mc / mc.sum()
        print("\n匹配方式花费占比:")
        for mt in sorted(set(mp.index) | set(mc.index)):
            x, y = mp.get(mt, 0), mc.get(mt, 0)
            mark = "  ◀" if abs(y - x) > 0.10 else ""
            print(f"  {mt:<10} {x:6.1%} → {y:6.1%}{mark}")
            if mark:
                signals.append(f"{mt} 花费占比 {x:.0%} → {y:.0%}")

    print("\n结论: " + ("【词结构有变化】" + "；".join(signals) + "\n→ 先向用户确认广告策略是否调整过" if signals else "词结构基本稳定"))

    show = gc.head(a.top).copy()
    show["上期花费"] = gp["spend"].reindex(show.index).fillna(0)
    show["状态"] = ["新进" if t not in gp.index else "" for t in show.index]
    show["ACOS"] = show["spend"] / show["sales"].where(show["sales"] > 0)
    print(f"\n本期花费 Top{a.top}:")
    with pd.option_context("display.width", 200, "display.max_colwidth", 40):
        print(show[["上期花费", "spend", "share", "clicks", "orders", "ACOS", "状态"]]
              .to_string(float_format=lambda v: f"{v:,.2f}"))

    cand = new_terms.sort_values("spend", ascending=False).head(20)
    print(f"\n新进花费词（待西柚查关联性，前 20）: {len(new_terms)} 个，合计花费 {new_terms['spend'].sum():,.2f}")
    if len(cand):
        print(cand[["clicks", "spend", "orders"]].to_string(float_format=lambda v: f"{v:,.2f}"))
    if a.out:
        with pd.ExcelWriter(a.out) as w:
            gc.assign(上期花费=gp["spend"].reindex(gc.index).fillna(0)).to_excel(w, sheet_name="本期词")
            new_terms.to_excel(w, sheet_name="新进词")
            gp[~gp.index.isin(gc.index)].to_excel(w, sheet_name="消失词")
        print(f"已导出: {a.out}")


# ---------------------------------------------------------------- filter

def cmd_filter(a):
    sop_gate(a.file, a.force)
    df = load_report(a.file)
    keys = [k for k in ("campaign", "ad_group", "match_type", "targeting", "search_term") if k in df.columns]
    if keys:
        df = df.groupby(keys, dropna=False)[NUMERIC].sum().reset_index()
    T = df[NUMERIC].sum()
    tot_ctr, tot_cvr, tot_acos = div(T["clicks"], T["impressions"]), div(T["orders"], T["clicks"]), div(T["spend"], T["sales"])
    df["CTR"] = df["clicks"] / df["impressions"].where(df["impressions"] > 0)
    df["CPC"] = df["spend"] / df["clicks"].where(df["clicks"] > 0)
    df["ACOS"] = df["spend"] / df["sales"].where(df["sales"] > 0)
    t = a.target_acos
    avg_cvr = tot_cvr if tot_cvr and not math.isnan(tot_cvr) else 0.1
    min_clicks = a.min_clicks or max(10, math.ceil(1.5 / avg_cvr))
    spend_med = df.loc[df["spend"] > 0, "spend"].median()

    print(f"合计: 花费 {T['spend']:,.2f}  订单 {T['orders']:.0f}  ACOS {fmt(tot_acos, 'pct')}  "
          f"CVR {fmt(tot_cvr, 'pct')}  CTR {fmt(tot_ctr, 'pct')}   目标ACOS {t:.0%}")
    print(f"阈值: 不出单点击 ≥ {min_clicks}，花费中位数 {spend_med:,.2f}")

    over = df[(df["spend"] >= spend_med) & (df["ACOS"] > t * 1.3)].copy()
    over["建议竞价"] = (over["CPC"] * (t / over["ACOS"]).clip(lower=0.7)).round(2)
    rules = {
        "烧钱不出单": (df[(df["clicks"] >= min_clicks) & (df["orders"] == 0)], "西柚查关联性：不相关→否定；相关→降竞价"),
        "ACOS超标": (over, "降竞价至'建议竞价'(单次调幅≤30%)"),
        "低效高曝光": (df[(df["impressions"] >= 1000) & (df["CTR"] < (tot_ctr or 0) * 0.5)], "检查相关性/主图/价格"),
        "优质词": (df[(df["orders"] >= 2) & (df["ACOS"] < t * 0.7)], "加价或开精准活动收割"),
    }
    show = keys + ["impressions", "clicks", "spend", "orders", "ACOS"]
    writer = pd.ExcelWriter(a.out) if a.out else None
    for name, (sub, action) in rules.items():
        sub = sub.sort_values("spend", ascending=False)
        print(f"\n=== {name}：{len(sub)} 条，花费合计 {sub['spend'].sum():,.2f}  → {action} ===")
        if len(sub):
            cols = show + (["CPC", "建议竞价"] if "建议竞价" in sub.columns else [])
            out = sub[cols].head(15).copy()
            out["ACOS"] = out["ACOS"].map(lambda v: fmt(v, "pct"))
            with pd.option_context("display.width", 220, "display.max_columns", 20, "display.max_colwidth", 40):
                print(out.to_string(index=False, float_format=lambda v: f"{v:,.2f}"))
        if writer:
            sub.to_excel(writer, sheet_name=name, index=False)
    if writer:
        writer.close()
        print(f"\n已导出: {a.out}")


# ---------------------------------------------------------------- harvest

ASIN_RE = re.compile(r"\bb0[0-9a-z]{8}\b")
EXACT_TYPES = {"exact", "精准", "精确"}


def cmd_harvest(a):
    """K1 收割词：已出单、ACOS 达标、但还没有单独精准投放的搜索词"""
    sop_gate(a.curr, a.force)
    parts = []
    for path, tag in ((a.curr, "curr"), (a.prev, "prev")):
        if not path:
            continue
        df = load_report(path)
        if "search_term" not in df.columns:
            sys.exit(f"[{path}] 找不到搜索词列（harvest 要用搜索词报告）")
        df["_period"] = tag
        parts.append(df)
    df = pd.concat(parts, ignore_index=True)
    for col in ("campaign", "match_type", "targeting"):
        if col not in df.columns:
            df[col] = ""
    df["term"] = df["search_term"].astype(str).str.strip().str.lower()
    df = df[df["term"].ne("") & df["term"].ne("nan")]
    mt = df["match_type"].astype(str).str.strip().str.lower()
    tg = df["targeting"].astype(str).str.strip().str.lower().str.strip('"')
    exact_kw = set(tg[mt.isin(EXACT_TYPES)])
    targeted_asins = set(ASIN_RE.findall(" ".join(tg[mt.str.contains("asin") | tg.str.contains("asin=")])))
    df["_src"] = ~mt.isin(EXACT_TYPES)

    g = df.groupby("term")[NUMERIC].sum()
    g["本期订单"] = df[df["_period"] == "curr"].groupby("term")["orders"].sum().reindex(g.index).fillna(0)
    g["上期订单"] = df[df["_period"] == "prev"].groupby("term")["orders"].sum().reindex(g.index).fillna(0)
    src = df[df["_src"]].groupby("term")["campaign"].agg(lambda s: "；".join(sorted(set(map(str, s)))))
    g["来源活动(加精准否定)"] = src.reindex(g.index).fillna("")
    g["CPC"] = g["spend"] / g["clicks"].where(g["clicks"] > 0)
    g["CVR"] = g["orders"] / g["clicks"].where(g["clicks"] > 0)
    g["ACOS"] = g["spend"] / g["sales"].where(g["sales"] > 0)
    t_ = a.target_acos
    rpc = g["sales"] / g["clicks"].where(g["clicks"] > 0)
    g["可承受CPC"] = (rpc * t_).round(2)
    g["建议精准竞价"] = (rpc * t_).clip(lower=g["CPC"] * 0.7, upper=g["CPC"] * 1.3).round(2)
    g["稳定"] = ((g["本期订单"] > 0) & (g["上期订单"] > 0)).map({True: "两期都出单", False: ""})
    for c in ("clicks", "orders", "本期订单", "上期订单"):
        g[c] = g[c].round().astype(int)
    brands = [b.strip().lower() for b in (a.brand or "").split(",") if b.strip()]
    g["品牌词"] = [("自家品牌" if any(b in term or b.replace(" ", "") in term.replace(" ", "") for b in brands) else "")
                  for term in g.index]
    is_asin = g.index.to_series().str.fullmatch(r"b0[0-9a-z]{8}")
    has_exact = g.index.isin(exact_kw)
    has_asin_target = g.index.isin(targeted_asins)
    good = (g["orders"] >= a.min_orders) & (g["ACOS"] <= t_)

    T = g[NUMERIC].sum()
    print(f"两期合并：{len(g)} 个搜索词，花费 {T['spend']:,.2f}，订单 {T['orders']:.0f}，"
          f"ACOS {fmt(div(T['spend'], T['sales']), 'pct')}   目标ACOS {t_:.0%}   收割条件：订单 ≥ {a.min_orders} 且 ACOS ≤ 目标")
    if not brands:
        print("提示：没传 --brand（自家品牌词，逗号分隔），品牌词不会单独标出；品牌词收割属于品牌防守，和拓流量分开写。")
    if not a.prev:
        print("⚠ 只给了一期（--prev 没传），7 天数据偏少，结论标\"推测\"。")

    cols = ["clicks", "spend", "orders", "本期订单", "上期订单", "CVR", "ACOS", "CPC", "可承受CPC", "建议精准竞价", "稳定", "品牌词",
            "来源活动(加精准否定)"]

    def show(title, sub, action, n=20):
        sub = sub.sort_values(["orders", "sales"], ascending=False)
        print(f"\n=== {title}：{len(sub)} 个，订单合计 {sub['orders'].sum():.0f}，花费 {sub['spend'].sum():,.2f}  → {action} ===")
        if len(sub):
            out = sub[cols].head(n).copy()
            for c in ("CVR", "ACOS"):
                out[c] = out[c].map(lambda v: fmt(v, "pct"))
            out["来源活动(加精准否定)"] = out["来源活动(加精准否定)"].str.slice(0, 60)
            with pd.option_context("display.width", 260, "display.max_columns", 20, "display.max_colwidth", 60):
                print(out.to_string(float_format=lambda v: f"{v:,.2f}"))
        return sub

    kw = show("K1 收割候选（关键词）", g[good & ~is_asin & ~has_exact],
              "开精准，竞价用'建议精准竞价'，来源活动加精准否定；'两期都出单'优先")
    asn = show("K1 收割候选（ASIN 定投）", g[good & is_asin & ~has_asin_target],
               "开 ASIN 精准定投（asinSameAs），来源活动加 ASIN 否定")
    done = g[good & ((~is_asin & has_exact) | (is_asin & has_asin_target))]
    print(f"\n已经单独精准投放 / 定投的出单词：{len(done)} 个（不重复建；要不要加价看 filter 的'优质词'）"
          + ("：" + "、".join(done.sort_values("orders", ascending=False).index[:10]) if len(done) else ""))
    watch = g[(g["orders"] == 1) & (g["ACOS"] <= t_) & ~has_exact]
    print(f"只出 1 单、ACOS 达标的词：{len(watch)} 个（数据不够，下期再看，不收割）"
          + ("：" + "、".join(watch.sort_values("sales", ascending=False).index[:10]) if len(watch) else ""))
    print("\n用法：这些是候选。第 7 步按 keyword-opportunities.md 6.6 的'诊断结果 → 用哪些来源'取舍；"
          "C 类（转化问题）只保留 K1，不加新词。")
    if a.out:
        with pd.ExcelWriter(a.out) as w:
            kw.to_excel(w, sheet_name="收割-关键词")
            asn.to_excel(w, sheet_name="收割-ASIN")
            done.to_excel(w, sheet_name="已精准")
            watch.to_excel(w, sheet_name="观察-1单")
        print(f"已导出: {a.out}")


# ---------------------------------------------------------------- structure

# 活动名 → 投放类型（按顺序匹配，先命中先算）。SB / SD 按 ad_type 单独归类。
CAMPAIGN_TYPES = [
    ("ASIN定投", r"asin|定投|商品投放|product[ _-]?target"),
    ("类目", r"类目|category|商品类型"),
    ("自动", r"自动|auto"),
    ("精准", r"精准|exact"),
    ("词组", r"词组|phrase"),
    ("广泛", r"广泛|broad"),
]


def campaign_type(name, ad_type):
    t = str(ad_type).lower()
    if t.startswith("sb"):
        return "SB"
    if t.startswith("sd"):
        return "SD"
    n = str(name).lower()
    for label, pat in CAMPAIGN_TYPES:
        if re.search(pat, n):
            return label
    return "其他SP"


def cmd_structure(a):
    df = read_any(a.file)
    df.columns = [str(c).strip().lower() for c in df.columns]
    need = {"date", "campaign", "spend"}
    if not need <= set(df.columns):
        sys.exit(f"campaigns_daily.csv 缺少列: {', '.join(sorted(need - set(df.columns)))}")
    df["date"] = pd.to_datetime(df["date"])
    for c in ("spend", "orders", "sales"):
        if c in df:
            df[c] = to_num(df[c])
    if "campaign_id" in df and df["campaign_id"].notna().any():
        # 活动常改名（名字里带日期）：同一个 campaign_id 统一用最后一天的名字，避免改名被当成"停掉一个、新开一个"
        df = df.sort_values("date")
        df["campaign_id"] = df["campaign_id"].astype(str)
        last_name = df.groupby("campaign_id")["campaign"].last()
        df["campaign"] = df["campaign_id"].map(last_name).fillna(df["campaign"])
    else:
        print("⚠ campaigns_daily.csv 没有 campaign_id 列：按活动名统计，活动中途改过名会被算成一停一开")
    df["类型"] = [campaign_type(n, t) for n, t in zip(df["campaign"], df.get("ad_type", [""] * len(df)))]
    cd = pd.Timestamp(a.change_date)
    W = pd.Timedelta(days=a.days)
    pre = df[(df["date"] >= cd - W) & (df["date"] < cd)]
    post = df[(df["date"] > cd) & (df["date"] <= cd + W)]
    if pre.empty or post.empty:
        sys.exit(f"改动日 {cd.date()} 前后 {a.days} 天没有数据（数据范围 {df['date'].min().date()} ~ {df['date'].max().date()}）")
    print(f"改动日 {cd.date()}：改动前 {pre['date'].min().date()}~{pre['date'].max().date()}，"
          f"改动后 {post['date'].min().date()}~{post['date'].max().date()}（改动当天不计）")
    print("活动类型按活动名判断（ASIN/定投 → ASIN定投，类目/商品类型，自动，精准，词组，广泛；SB、SD 按广告类型），"
          "名字不规范的归'其他SP'\n")
    sp_pre, sp_post = pre.groupby("类型")["spend"].sum(), post.groupby("类型")["spend"].sum()
    tot_pre, tot_post = sp_pre.sum(), sp_post.sum()
    rows = []
    for k in sorted(set(sp_pre.index) | set(sp_post.index),
                    key=lambda x: (-sp_pre.get(x, 0), -sp_post.get(x, 0), x)):  # 并列时顺序固定
        p, q = sp_pre.get(k, 0.0), sp_post.get(k, 0.0)
        rows.append([k, f"{p:,.2f}", f"{div(p, tot_pre):.1%}", f"{q:,.2f}", f"{div(q, tot_post):.1%}",
                     f"{(div(q, tot_post) - div(p, tot_pre)) * 100:+.1f}pp"])
    hdr = ["类型", "改动前花费", "前占比", "改动后花费", "后占比", "占比变化"]
    print("| " + " | ".join(hdr) + " |\n|" + "---|" * len(hdr))
    for r in rows:
        print("| " + " | ".join(r) + " |")
    print(f"\n日均花费：改动前 {tot_pre / a.days:,.2f}，改动后 {tot_post / a.days:,.2f}")
    a_pre = pre.groupby("campaign")["spend"].sum()
    a_post = post.groupby("campaign")["spend"].sum()
    stopped = [c for c in a_pre.index if a_pre[c] > 0 and a_post.get(c, 0) == 0]
    started = [c for c in a_post.index if a_post[c] > 0 and a_pre.get(c, 0) == 0]
    for label, names, src in (("改动后不再花费的活动（暂停数以 op_log 为准）", stopped, a_pre), ("改动后新出现花费的活动（新开/重开）", started, a_post)):
        if names:
            print(f"\n{label}：{len(names)} 个，合计 {src[names].sum():,.2f}")
            for c in sorted(names, key=lambda x: -src[x]):
                print(f"  - [{campaign_type(c, pre.loc[pre['campaign'] == c, 'ad_type'].iloc[0] if 'ad_type' in pre and c in set(pre['campaign']) else '')}] {c}  ({src[c]:,.2f})")
    # 可直接贴进"用户说法核对表"的汇总行
    def share(k, s, tot):
        return div(s.get(k, 0.0), tot)
    print("\n—— 核对表可直接引用 ——")
    asin_pre, asin_post = sp_pre.get("ASIN定投", 0.0), sp_post.get("ASIN定投", 0.0)
    st_asin = [c for c in stopped if campaign_type(c, "") == "ASIN定投"]
    top = "；".join(sorted(stopped, key=lambda x: -a_pre[x])[:5])
    print(f"[关停定投] ASIN定投花费占比 {share('ASIN定投', sp_pre, tot_pre):.1%}→{share('ASIN定投', sp_post, tot_post):.1%}，"
          f"ASIN定投花费减少 {1 - div(asin_post, asin_pre):.1%}；改动后不再花费的活动 {len(stopped)} 个（其中 ASIN定投 {len(st_asin)} 个；暂停数以 op_log 为准），"
          f"合计改动前花费 {a_pre[stopped].sum() if stopped else 0:,.2f}；前 5 个：{top or '无'}")
    for k in ("广泛", "精准", "词组"):
        print(f"[改成{k}] {k}花费占比 {share(k, sp_pre, tot_pre):.1%}→{share(k, sp_post, tot_post):.1%}"
              f"（{(share(k, sp_post, tot_post) - share(k, sp_pre, tot_pre)) * 100:+.1f}pp）")
    print("\n用法：用户说'关停 X% 定投'看 ASIN定投 的占比变化和停掉名单；说'改成广泛/精准'看对应类型占比变化。"
          "方向一致写'一致'，相反写'不一致'，改动日不在数据范围内写'无法核对'。")


# ---------------------------------------------------------------- oplog

AUTO_OPERATORS = {"亚马逊日志", "amazon", "Amazon", "system", "系统"}
OPLOG_GROUPS = [
    ("状态（暂停/开启）", r"^(?:STATUS|STATE)$"),
    ("预算", r"BUDGET"),
    ("竞价", r"BID"),
    ("广告位溢价", r"PLACEMENT"),
    ("竞价策略", r"STRATEGY"),
]


def cmd_oplog(a):
    df = read_any(a.file)
    df.columns = [str(c).strip().lower() for c in df.columns]
    need = {"time", "campaign", "field", "old_value", "new_value", "operator"}
    if not need <= set(df.columns):
        sys.exit(f"op_log.csv 缺少列: {', '.join(sorted(need - set(df.columns)))}")
    df["day"] = df["time"].astype(str).str[:10]
    if a.start:
        df = df[df["day"] >= a.start]
    if a.end:
        df = df[df["day"] <= a.end]
    if not a.all:
        df = df[~df["operator"].astype(str).isin(AUTO_OPERATORS)]
    field = df["field"].astype(str).str.upper()
    print(f"操作日志 {df['day'].min()} ~ {df['day'].max()}，{len(df)} 条"
          f"（{'含' if a.all else '不含'}亚马逊/系统自动记录；操作人不显示）")
    for label, pat in OPLOG_GROUPS:
        sub = df[field.str.contains(pat, regex=True)]
        if sub.empty:
            continue
        print(f"\n=== {label}：{len(sub)} 条 ===")
        if label.startswith("状态"):
            for (day, new), g in sub.groupby(["day", sub["new_value"].astype(str).str.lower()]):
                names = sorted(set(g["campaign"].astype(str)))
                print(f"{day}  → {new}  {len(names)} 个活动: " + "；".join(names[:8]) + (" …" if len(names) > 8 else ""))
        else:
            for day, g in sub.groupby("day"):
                ex = g.head(3).apply(lambda r: f"{r['campaign']}: {r['old_value']}→{r['new_value']}", axis=1)
                print(f"{day}  {len(g)} 条  例: " + "；".join(ex) + (" …" if len(g) > 3 else ""))
    print("\n用法：把这里的日期和 trend 输出的'第一个异常的变量'起点对照；"
          "用户说的调整（关停定投、改匹配、降预算）要在这里找到对应记录。")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    f = sp.add_parser("trend", help="daily.csv 日/周/月对比")
    f.add_argument("--file", required=True)
    f.add_argument("--date", help="锚点日期 yyyy-MM-dd，默认数据最后一天")
    f.add_argument("--ly", help="去年同期数据，默认同目录的 daily_ly.csv（没有就不算年同比）")
    f.add_argument("--out", help="导出 CSV")
    f.set_defaults(func=cmd_trend)
    t = sp.add_parser("terms", help="两期搜索词结构对比")
    t.add_argument("--prev", required=True)
    t.add_argument("--curr", required=True)
    t.add_argument("--top", type=int, default=15)
    t.add_argument("--out", help="导出 Excel")
    t.add_argument("--force", action="store_true", help="跳过 SOP 顺序检查（不推荐）")
    t.set_defaults(func=cmd_terms)
    g = sp.add_parser("filter", help="搜索词/关键词组合筛选")
    g.add_argument("--file", required=True)
    g.add_argument("--target-acos", type=rate_arg, required=True, help="目标 ACOS，写 55%%、55 或 0.55 都行")
    g.add_argument("--min-clicks", type=int, help="不出单点击阈值，默认自动")
    g.add_argument("--out", help="导出 Excel")
    g.add_argument("--force", action="store_true", help="跳过 SOP 顺序检查（不推荐）")
    g.set_defaults(func=cmd_filter)
    h = sp.add_parser("harvest", help="K1 收割词：已出单、ACOS 达标、还没单独精准投放的搜索词")
    h.add_argument("--curr", required=True, help="st_curr.csv")
    h.add_argument("--prev", help="st_prev.csv（建议传，两期合并 14 天）")
    h.add_argument("--target-acos", type=rate_arg, required=True, help="目标 ACOS，写 55%%、55 或 0.55 都行")
    h.add_argument("--min-orders", type=int, default=2, help="收割的最少订单数，默认 2")
    h.add_argument("--brand", help="自家品牌词，逗号分隔（取 asin-profiles.md 的'品牌词'），用来单独标出品牌词")
    h.add_argument("--out", help="导出 Excel")
    h.add_argument("--force", action="store_true", help="跳过 SOP 顺序检查（不推荐）")
    h.set_defaults(func=cmd_harvest)
    s = sp.add_parser("structure", help="改动前后的活动类型花费占比（核对'关停定投''改成广泛'）")
    s.add_argument("--file", required=True, help="campaigns_daily.csv")
    s.add_argument("--change-date", required=True, help="改动日 yyyy-MM-dd（从 oplog 找）")
    s.add_argument("--days", type=int, default=14, help="改动前后各取几天，默认 14")
    s.set_defaults(func=cmd_structure)
    o = sp.add_parser("oplog", help="广告操作日志按日期汇总（暂停/开启、预算、竞价、溢价）")
    o.add_argument("--file", required=True, help="op_log.csv")
    o.add_argument("--from", dest="start", help="开始日期 yyyy-MM-dd")
    o.add_argument("--to", dest="end", help="结束日期 yyyy-MM-dd")
    o.add_argument("--all", action="store_true", help="包含亚马逊/系统自动产生的记录")
    o.set_defaults(func=cmd_oplog)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
