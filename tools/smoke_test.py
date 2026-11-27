"""ad_diag.py 冒烟测试：用合成数据（不含任何真实店铺数据）把 6 个子命令都跑一遍，检查退出码和关键输出。

用法：
    python tools/smoke_test.py                      # 测 Claude 版（源）和通用版两份脚本
    python tools/smoke_test.py path/to/ad_diag.py   # 只测指定脚本

build_portable.py --check 会自动调用它。全部通过返回 0。
"""
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = [
    ROOT / "plugins/amazon-ad-diagnosis/skills/amazon-ad-diagnosis/scripts/ad_diag.py",
    ROOT / "portable/amazon-ad-diagnosis/scripts/ad_diag.py",
]
ANCHOR = pd.Timestamp("2026-03-31")
CHANGE = ANCHOR - pd.Timedelta(days=20)   # 改动日：暂停定投


def daily(start, sess_hi, sess_lo, ad_orders_hi, ad_orders_lo):
    """60 天：前 30 天流量高，后 30 天流量低；CVR 固定 30%"""
    rows = []
    for i in range(60):
        d = start + pd.Timedelta(days=i)
        hi = i < 30
        sess = sess_hi if hi else sess_lo
        ao = ad_orders_hi if hi else ad_orders_lo
        orders = round(sess * 0.30)
        clicks = ao * 5
        rows.append(dict(date=d.date(), impressions=clicks * 150, clicks=clicks, spend=clicks * 2.0,
                         ad_orders=ao, ad_sales=ao * 25.0, budget="", total_orders=orders,
                         total_sales=orders * 25.0, sessions=sess, organic_impressions="",
                         price=24.99, rating=4.6, inventory=5000))
    return pd.DataFrame(rows)


def build_fixture(d: Path):
    start = ANCHOR - pd.Timedelta(days=59)
    # 今年：流量 300 → 200（-33%），广告订单 30 → 15（-50%）
    daily(start, 300, 200, 30, 15).to_csv(d / "daily.csv", index=False, encoding="utf-8-sig")
    # 去年同期（−364 天）：流量也是 300 → 200（季节性），广告订单 20 → 24（去年在涨）
    daily(start - pd.Timedelta(days=364), 300, 200, 20, 24).to_csv(d / "daily_ly.csv", index=False, encoding="utf-8-sig")

    camp = []
    for i in range(60):
        dt = start + pd.Timedelta(days=i)
        # id 1：广泛，中途改名（改名不应被当成停掉）
        name1 = "广泛-A-v1" if dt < CHANGE else "广泛-A-v2"
        camp.append((dt.date(), "1", name1, "sp", 3000, 30, 60.0, 3, 75.0, 100))
        # id 2：ASIN 定投，改动日之后停掉
        if dt <= CHANGE:
            camp.append((dt.date(), "2", "ASIN-定投-竞品X", "sp", 2000, 20, 40.0, 1, 25.0, 50))
        # id 3：精准，一直在
        camp.append((dt.date(), "3", "精准-B", "sp", 1000, 15, 30.0, 2, 50.0, 50))
        # id 4：SB
        camp.append((dt.date(), "4", "SB-自动", "sb2", 1500, 10, 20.0, 1, 25.0, 30))
    pd.DataFrame(camp, columns=["date", "campaign_id", "campaign", "ad_type", "impressions", "clicks",
                                "spend", "orders", "sales", "budget"]).to_csv(
        d / "campaigns_daily.csv", index=False, encoding="utf-8-sig")

    st_cols = ["campaign", "ad_group", "match_type", "targeting", "search_term", "impressions", "clicks",
               "spend", "orders", "sales"]
    st_prev = [("广泛-A-v2", "g1", "broad", "magnesium", "magnesium complex", 2000, 40, 80.0, 4, 100.0),
               ("精准-B", "g2", "exact", "magnesium 7", "magnesium 7", 800, 20, 40.0, 3, 75.0)]
    st_curr = [("广泛-A-v2", "g1", "broad", "magnesium", "magnesium complex", 2000, 40, 80.0, 1, 25.0),
               ("广泛-A-v2", "g1", "broad", "magnesium", "magnesium sulfate", 1500, 15, 30.0, 0, 0.0),
               ("精准-B", "g2", "exact", "magnesium 7", "magnesium 7", 800, 20, 40.0, 4, 100.0),
               ("SB-自动", "g3", "theme", "auto", "magnesium for men", 300, 6, 12.0, 2, 50.0),
               # harvest 用：ASIN 搜索词、自家品牌词
               ("广泛-A-v2", "g1", "broad", "magnesium", "b0abcd1234", 100, 5, 10.0, 2, 50.0),
               ("广泛-A-v2", "g1", "broad", "magnesium", "acme magnesium", 50, 4, 8.0, 3, 75.0)]
    pd.DataFrame(st_prev, columns=st_cols).to_csv(d / "st_prev.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(st_curr, columns=st_cols).to_csv(d / "st_curr.csv", index=False, encoding="utf-8-sig")

    op = [(f"{CHANGE.date()} 10:00:00", "2", "ASIN-定投-竞品X", "campaigns:ASIN-定投-竞品X", "STATUS", "enabled", "paused", "运营A"),
          (f"{CHANGE.date()} 10:05:00", "1", "广泛-A-v1", "campaigns:广泛-A-v1", "BUDGET_AMOUNT", "100", "150", "运营A"),
          (f"{CHANGE.date()} 11:00:00", "1", "广泛-A-v1", "campaigns:广泛-A-v1", "IN_BUDGET", "true", "false", "亚马逊日志")]
    pd.DataFrame(op, columns=["time", "campaign_id", "campaign", "object", "field", "old_value", "new_value",
                              "operator"]).to_csv(d / "op_log.csv", index=False, encoding="utf-8-sig")


def run(script, args):
    r = subprocess.run([sys.executable, "-I", str(script), *args], capture_output=True)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


def check(script: Path) -> list[str]:
    fails = []

    def expect(name, cond, out=""):
        if not cond:
            fails.append(f"{script.parent.parent.name}/{name}" + (f"\n      输出片段: {out[-300:]!r}" if out else ""))

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp) / "data" / "ad-data" / "B0TEST00001_2026-03-31"
        d.mkdir(parents=True)
        build_fixture(d)

        code, out = run(script, ["trend", "--file", str(d / "daily.csv")])
        expect("trend 退出码 0", code == 0, out)
        for key in ("跨周期一致性", "第①层 市场需求", "主周期", "30天同比", "去年同期月环比"):
            expect(f"trend 输出含「{key}」", key in out, out)
        matrix = out.split("跨周期一致性", 1)[-1].split("说明：", 1)[0]

        def row(name):
            return next((l for l in matrix.splitlines() if l.startswith(f"| {name} |")), "")
        expect("trend：Sessions 判为偏季节性（去年同期也这样跌）", "偏季节性" in row("日均流量(Sessions)"), matrix)
        expect("trend：广告订单判为今年真的变差（去年同期在涨）", "今年真的变差" in row("广告订单"), matrix)

        code, out = run(script, ["terms", "--prev", str(d / "st_prev.csv"), "--curr", str(d / "st_curr.csv")])
        expect("terms 缺 rootcause 时被门禁拦下（非 0 + ⛔）", code != 0 and "⛔" in out, out)
        code, out = run(script, ["filter", "--file", str(d / "st_curr.csv"), "--target-acos", "55%"])
        expect("filter 缺 rootcause 时被门禁拦下", code != 0 and "⛔" in out, out)
        expect("门禁提示不建议 --force", "或加 --force" not in out, out)
        harvest = ["harvest", "--curr", str(d / "st_curr.csv"), "--prev", str(d / "st_prev.csv"),
                   "--target-acos", "55%", "--brand", "acme"]
        code, out = run(script, harvest)
        expect("harvest 缺 rootcause 时被门禁拦下", code != 0 and "⛔" in out, out)

        (d / "rootcause_external.md").write_text("x", encoding="utf-8")
        (d / "rootcause_internal.md").write_text("x", encoding="utf-8")
        code, out = run(script, ["terms", "--prev", str(d / "st_prev.csv"), "--curr", str(d / "st_curr.csv")])
        expect("terms 有 rootcause 后正常运行", code == 0 and "Top10" in out, out)
        code, out = run(script, ["filter", "--file", str(d / "st_curr.csv"), "--target-acos", "55%"])
        expect("filter 有 rootcause 后正常运行", code == 0 and "目标ACOS 55%" in out, out)

        code, out = run(script, harvest)
        expect("harvest 退出码 0", code == 0, out)
        kw = out.split("K1 收割候选（关键词）", 1)[-1].split("K1 收割候选（ASIN", 1)[0]
        asin = out.split("K1 收割候选（ASIN 定投）", 1)[-1].split("已经单独精准投放", 1)[0]
        done = out.split("已经单独精准投放", 1)[-1].splitlines()[0]
        expect("harvest：出单且 ACOS 达标的词进收割候选", "magnesium for men" in kw, out)
        expect("harvest：收割候选带来源活动（要加精准否定）", "SB-自动" in kw, out)
        expect("harvest：已有精准投放的词不重复建", "magnesium 7" not in kw and "magnesium 7" in done, out)
        expect("harvest：ACOS 超标的词不收割", "magnesium complex" not in kw, out)
        expect("harvest：ASIN 搜索词单独列", "b0abcd1234" in asin and "b0abcd1234" not in kw, out)
        expect("harvest：自家品牌词被标出", "自家品牌" in kw and "acme magnesium" in kw, out)

        code, out = run(script, ["oplog", "--file", str(d / "op_log.csv")])
        expect("oplog 退出码 0", code == 0, out)
        expect("oplog 列出暂停", "paused" in out and "ASIN-定投-竞品X" in out, out)
        expect("oplog 默认不含亚马逊自动记录", "IN_BUDGET" not in out, out)

        code, out = run(script, ["structure", "--file", str(d / "campaigns_daily.csv"), "--change-date", str(CHANGE.date())])
        expect("structure 退出码 0", code == 0, out)
        expect("structure：改名的活动不算停掉", "广泛-A-v1" not in out.split("改动后不再花费的活动")[-1].split("改动后新出现")[0], out)
        expect("structure：停掉的定投被列出", "ASIN-定投-竞品X" in out and "[关停定投]" in out, out)

        empty = d / "empty.csv"
        empty.write_text("date,total_orders\n", encoding="utf-8-sig")
        code, out = run(script, ["trend", "--file", str(empty)])
        expect("trend 空文件时报错退出", code != 0 and "没有数据" in out, out)
    return fails


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    targets = [Path(a) for a in sys.argv[1:]] or [s for s in SCRIPTS if s.exists()]
    fails = []
    for s in targets:
        fails += check(s)
    if fails:
        print("冒烟测试未通过：")
        for f in fails:
            print("  ✗", f)
        return 1
    print(f"冒烟测试通过：{len(targets)} 份脚本 × 6 个子命令 + 门禁 + 边界情况")
    return 0


if __name__ == "__main__":
    sys.exit(main())
