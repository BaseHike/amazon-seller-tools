"""从 Claude 版 skill 生成通用版（Codex / WorkBuddy 等），并做发布前检查。

用法：
    python tools/build_portable.py           # 重新生成 portable/amazon-ad-diagnosis/
    python tools/build_portable.py --check   # 只检查：通用版是否和源一致、版本号、私有数据

唯一的源是 plugins/amazon-ad-diagnosis/skills/amazon-ad-diagnosis/。
通用版只在四处和源不同：
  1. SKILL.md 换成 tools/portable/SKILL.md
  2. 多一个 README.md（tools/portable/README.md，安装说明）
  3. 多一个 references/portable-runtime.md
  4. 含 Claude 专用说法的 reference 文件，顶部加一段提示
其他文件（references、scripts）原样复制。不要直接改 portable/ 下的文件。
"""
import argparse
import filecmp
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "plugins" / "amazon-ad-diagnosis" / "skills" / "amazon-ad-diagnosis"
DST = ROOT / "portable" / "amazon-ad-diagnosis"
OVERLAY = ROOT / "tools" / "portable"

CLAUDE_TERMS = re.compile(r"子代理|Agent 工具|AskUserQuestion|ToolSearch|CLAUDE_SKILL_DIR|claude mcp add|subagent_type|Base directory")
BANNER = (
    "> **通用版提示**：本文件和 Claude 版共用。文中的“子代理 / 主代理”都由你自己按顺序做；"
    "AskUserQuestion、ToolSearch、Agent 工具、`claude mcp add` 等说法，"
    "按 `references/portable-runtime.md` 换成你所在软件的做法。\n\n"
)
SKIP = {"__pycache__", ".pytest_cache", "data"}  # data/ 是用户私有 ASIN 资料，不进通用版


def build(dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(SRC, dst, ignore=shutil.ignore_patterns(*SKIP, "*.pyc"))
    # 注意：只忽略 skill 根下的 data/；references、scripts 里没有叫 data 的目录
    shutil.copyfile(OVERLAY / "SKILL.md", dst / "SKILL.md")
    shutil.copyfile(OVERLAY / "README.md", dst / "README.md")
    shutil.copyfile(OVERLAY / "portable-runtime.md", dst / "references" / "portable-runtime.md")
    for md in sorted((dst / "references").glob("*.md")):
        if md.name == "portable-runtime.md":
            continue
        text = md.read_text(encoding="utf-8")
        if CLAUDE_TERMS.search(text):
            lines = text.split("\n", 1)
            # 标题行之后插入提示
            if lines[0].startswith("#") and len(lines) == 2:
                text = lines[0] + "\n\n" + BANNER + lines[1].lstrip("\n")
            else:
                text = BANNER + text
            md.write_text(text, encoding="utf-8", newline="\n")


def same_tree(a: Path, b: Path) -> list[str]:
    diffs = []
    fa = {p.relative_to(a) for p in a.rglob("*") if p.is_file() and not (SKIP & set(p.relative_to(a).parts)) and p.suffix != ".pyc"}
    fb = {p.relative_to(b) for p in b.rglob("*") if p.is_file() and not (SKIP & set(p.relative_to(b).parts)) and p.suffix != ".pyc"}
    for rel in sorted(fa ^ fb):
        diffs.append(f"文件只在一边存在: {rel}")
    for rel in sorted(fa & fb):
        if not filecmp.cmp(a / rel, b / rel, shallow=False):
            diffs.append(f"内容不同: {rel}")
    return diffs


PRIVATE_PATTERNS = [
    # 模板之外出现真实 ASIN 记录（"## US B0XXXXXXXX" 这种模板占位符除外）
    (re.compile(r"^## [A-Z]{2} B0(?!X{8})[0-9A-Z]{8}\b", re.M), "asin-profiles 里有真实 ASIN 记录"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "邮箱地址"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}"), "疑似令牌"),
    (re.compile(r"[A-Za-z]:\\\\?[^\s`\"']*电商"), "本机绝对路径"),
]
TEXT_EXT = {".md", ".py", ".json", ".txt", ".toml", ".yaml", ".yml"}


def git_visible_files():
    """会被提交的文件：已跟踪 + 未跟踪但没被 .gitignore 忽略的。私有的 data/ 不在其中。"""
    import subprocess
    try:
        out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ROOT,
                             capture_output=True, check=True).stdout.decode("utf-8")
        return [ROOT / f for f in out.split("\0") if f]
    except (OSError, subprocess.CalledProcessError):
        return [p for p in ROOT.rglob("*") if ".git" not in p.parts and "data" not in p.parts]


def privacy_scan() -> list[str]:
    hits = []
    for p in git_visible_files():
        if not p.is_file() or p.suffix not in TEXT_EXT:
            continue
        if p == Path(__file__).resolve():
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for pat, label in PRIVATE_PATTERNS:
            m = pat.search(text)
            if m:
                hits.append(f"{p.relative_to(ROOT)}: {label} → {m.group(0)[:60]}")
    return hits


def version_check() -> list[str]:
    plugin = json.loads((ROOT / "plugins/amazon-ad-diagnosis/.claude-plugin/plugin.json").read_text(encoding="utf-8"))
    market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
    mv = next((p.get("version") for p in market["plugins"] if p["name"] == plugin["name"]), None)
    return [] if mv == plugin["version"] else [f"版本不一致: plugin.json {plugin['version']} / marketplace.json {mv}"]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只检查，不生成")
    a = ap.parse_args()
    if not a.check:
        build(DST)
        print(f"已生成: {DST.relative_to(ROOT)}")
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        fresh = Path(tmp) / "amazon-ad-diagnosis"
        build(fresh)
        if not DST.exists():
            problems.append("portable/amazon-ad-diagnosis 不存在，先运行 build_portable.py")
        else:
            problems += [f"通用版和源不同步 — {d}" for d in same_tree(fresh, DST)]
    problems += version_check()
    problems += privacy_scan()
    # 冒烟测试：合成数据把两份 ad_diag.py 的 6 个子命令都跑一遍
    import subprocess
    r = subprocess.run([sys.executable, "-I", str(ROOT / "tools" / "smoke_test.py")], capture_output=True)
    smoke = (r.stdout + r.stderr).decode("utf-8", "replace").strip()
    if r.returncode != 0:
        problems.append("冒烟测试未通过：\n" + smoke)
    if problems:
        print("检查未通过：")
        for p in problems:
            print("  ✗", p)
        return 1
    print("检查通过：通用版与源同步，版本号一致，未发现私有数据。" + smoke)
    return 0


if __name__ == "__main__":
    sys.exit(main())
