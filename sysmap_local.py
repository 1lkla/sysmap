#!/usr/bin/env python3
"""sysmap-local — 100% 本地的「已登录系统架构 → 知识图谱」流水线。

把原本依赖云端 Claude 编排的能力，落地为一个确定性的本地编排器：

    your logged-in Chrome
            │  (CDP, read-only, via browser-harness — 本地)
            ▼
    crawl.py  ──►  <out>/raw/*.md   (6 张图的显式关系句, 纯代码, 无 LLM)
            │
            ▼
    graphify extract  --backend ollama   (本地 LLM 抽取/补边)
    graphify cluster-only --backend ollama (本地 LLM 社区命名 + 报告 + HTML)
            │
            ▼
    知识图谱: graph.json + graph.html + GRAPH_REPORT.md

关键点：侦察阶段(crawl.py)完全确定、无需任何模型，6 张图的关系已由代码写成显式句子。
所以即便用本地小模型，图谱质量也几乎不掉点 —— 这就是"本地化也能 100%"的原因。

用法:
    python3 sysmap_local.py build <start-url> [--max 40] [--out ./sysmap-out]
                                  [--backend ollama] [--model glm-4.7-flash:latest]
    python3 sysmap_local.py query "<问题>" [--out ./sysmap-out] [--synthesize]

安全: 只读侦察。仅对你拥有或已获授权的系统运行。遇到登录墙会停止，不输入任何凭据。
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CRAWL = HERE / "crawl.py"


def die(msg, code=1):
    print(f"\n[sysmap-local] 错误: {msg}", file=sys.stderr)
    sys.exit(code)


def find_tool(name, hint):
    p = shutil.which(name)
    if not p:
        die(f"找不到 `{name}`。{hint}")
    return p


def graphify_bin():
    return find_tool(
        "graphify",
        "请先安装: `uv tool install graphifyy` 或 `pip install graphifyy`。",
    )


def browser_harness_bin():
    return find_tool(
        "browser-harness",
        "请确认 browser-harness 已安装并在 $PATH 上（用户的本地 CDP 浏览器控制器）。",
    )


def ollama_up(base_url):
    """确认本地 Ollama 在线，并返回已安装模型名列表。"""
    tags = base_url.rstrip("/").replace("/v1", "") + "/api/tags"
    try:
        with urllib.request.urlopen(tags, timeout=4) as r:
            data = json.loads(r.read())
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return None


# ---------------------------------------------------------------- build

def cmd_build(args):
    out = Path(args.out).resolve()
    raw = out / "raw"
    out.mkdir(parents=True, exist_ok=True)

    gbin = graphify_bin()
    bh = browser_harness_bin()

    # 后端预检：ollama 需要 daemon + 模型在线
    genv = dict(os.environ)
    if args.backend == "ollama":
        base = args.ollama_base or os.environ.get(
            "OLLAMA_BASE_URL", "http://localhost:11434/v1"
        )
        genv["OLLAMA_BASE_URL"] = base
        genv["OLLAMA_MODEL"] = args.model
        models = ollama_up(base)
        if models is None:
            die(
                f"Ollama 未在线 ({base})。先运行 `ollama serve`（或打开 Ollama.app）。"
            )
        if args.model not in models and args.model.split(":")[0] not in [
            m.split(":")[0] for m in models
        ]:
            print(
                f"[sysmap-local] 警告: 本地未发现模型 '{args.model}'。"
                f"已安装: {', '.join(models) or '(空)'}。"
                f"\n  Ollama 会在首次调用时尝试拉取；或先 `ollama pull {args.model}`。"
            )
        print(f"[sysmap-local] 后端=ollama 模型={args.model} @ {base}")
    else:
        print(f"[sysmap-local] 后端={args.backend}（使用对应的 API key 环境变量）")

    # ---- 1. 只读侦察 -------------------------------------------------
    print(f"\n[sysmap-local] 1/3 侦察 {args.url} (max={args.max}) → {raw}")
    cenv = dict(os.environ)
    cenv["SYSMAP_URL"] = args.url
    cenv["SYSMAP_MAX_PAGES"] = str(args.max)
    cenv["SYSMAP_OUT"] = str(out)
    with open(CRAWL, "rb") as fh:
        rc = subprocess.run([bh], stdin=fh, env=cenv).returncode
    if rc != 0:
        die("侦察阶段失败（browser-harness 返回非零）。")

    mds = sorted(raw.glob("*.md"))
    if not mds:
        die(f"侦察没有产出 markdown（{raw} 为空）。可能撞上登录墙——请先在浏览器登录。")
    # 路由数粗检
    routes_md = raw / "01_routes.md"
    if routes_md.exists() and routes_md.read_text(encoding="utf-8").count("## Route ") == 0:
        print(
            "[sysmap-local] 警告: 抓到 0 条路由。起始页可能还没加载同源链接，"
            "换一个更深的 URL 再试。"
        )

    # ---- 2. 本地抽取 → graph.json -----------------------------------
    print(f"\n[sysmap-local] 2/3 抽取实体/关系 (graphify extract, backend={args.backend})")
    rc = subprocess.run(
        [gbin, "extract", str(raw), "--backend", args.backend], env=genv
    ).returncode
    if rc != 0:
        die("graphify extract 失败。")

    graph = raw / "graphify-out" / "graph.json"
    if not graph.exists():
        die(f"未生成 {graph}。")

    # ---- 3. 聚类命名 + 报告 + HTML ----------------------------------
    print(f"\n[sysmap-local] 3/3 社区命名 + 报告 + HTML (graphify cluster-only)")
    rc = subprocess.run(
        [gbin, "cluster-only", str(raw), "--backend", args.backend], env=genv
    ).returncode
    if rc != 0:
        print("[sysmap-local] 警告: cluster-only 失败，社区可能保留占位名。图谱仍可用。")

    gout = raw / "graphify-out"
    print("\n[sysmap-local] 完成。产物:")
    for f in ("graph.html", "GRAPH_REPORT.md", "graph.json"):
        p = gout / f
        if p.exists():
            print(f"  {p}")

    _print_report_sections(gout / "GRAPH_REPORT.md")
    print(
        f"\n下一步可问图谱: "
        f'python3 {Path(__file__).name} query "哪些路由调用了文件处理 API?" --out {args.out}'
    )


def _print_report_sections(report):
    if not report.exists():
        return
    text = report.read_text(encoding="utf-8")
    wanted = ("God Nodes", "Surprising Connections", "Suggested Questions")
    lines = text.splitlines()
    blocks = []
    cur, capture = [], False
    for ln in lines:
        if ln.startswith("## ") or ln.startswith("# "):
            if capture and cur:
                blocks.append("\n".join(cur))
            cur = []
            capture = any(w.lower() in ln.lower() for w in wanted)
        if capture:
            cur.append(ln)
    if capture and cur:
        blocks.append("\n".join(cur))
    if blocks:
        print("\n" + "=" * 60)
        print("\n\n".join(blocks))
        print("=" * 60)


# ---------------------------------------------------------------- query

def cmd_query(args):
    gbin = graphify_bin()
    graph = Path(args.out).resolve() / "raw" / "graphify-out" / "graph.json"
    if not graph.exists():
        die(f"找不到图谱 {graph}。先运行 `build`。")

    cmd = [gbin, "query", args.question, "--graph", str(graph)]
    if args.dfs:
        cmd.append("--dfs")
    if args.budget:
        cmd += ["--budget", str(args.budget)]
    res = subprocess.run(cmd, capture_output=True, text=True)
    context = res.stdout.strip()
    print(context)
    if res.returncode != 0 and not context:
        die(res.stderr.strip() or "graphify query 失败。")

    if args.synthesize and context:
        print("\n" + "-" * 60 + "\n[本地模型综述]\n")
        _synthesize(args, context)


def _synthesize(args, context):
    base = args.ollama_base or os.environ.get(
        "OLLAMA_BASE_URL", "http://localhost:11434/v1"
    )
    gen = base.rstrip("/").replace("/v1", "") + "/api/generate"
    prompt = (
        "你是系统架构分析助手。下面是从某已登录 Web 系统的知识图谱里检索到的子图上下文。"
        "只依据这些内容回答问题，不要编造图中不存在的路由/API/权限关系。"
        f"\n\n问题: {args.question}\n\n图谱上下文:\n{context}\n\n回答:"
    )
    payload = json.dumps(
        {"model": args.model, "prompt": prompt, "stream": False}
    ).encode()
    try:
        req = urllib.request.Request(
            gen, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=180) as r:
            print(json.loads(r.read()).get("response", "").strip())
    except Exception as e:
        print(f"[本地综述失败: {e}] —— 上面的图谱检索结果仍然有效。")


# ---------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(
        prog="sysmap_local.py",
        description="100% 本地的『已登录系统 → 知识图谱』流水线",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="侦察目标系统并构建知识图谱")
    b.add_argument("url", help="已登录系统的起始 URL")
    b.add_argument("--max", type=int, default=40, help="最多抓取路由数 (默认 40)")
    b.add_argument("--out", default="./sysmap-out", help="输出目录 (默认 ./sysmap-out)")
    b.add_argument(
        "--backend",
        default="ollama",
        help="graphify LLM 后端: ollama|openai|deepseek|gemini|claude-cli|... (默认 ollama)",
    )
    b.add_argument(
        "--model",
        default=os.environ.get("OLLAMA_MODEL", "glm-4.7-flash:latest"),
        help="本地模型名 (默认 glm-4.7-flash:latest)",
    )
    b.add_argument("--ollama-base", default=None, help="覆盖 OLLAMA_BASE_URL")
    b.set_defaults(func=cmd_build)

    q = sub.add_parser("query", help="向已构建的图谱提问")
    q.add_argument("question", help="自然语言问题")
    q.add_argument("--out", default="./sysmap-out", help="build 时用的输出目录")
    q.add_argument("--dfs", action="store_true", help="深度优先（追踪单条路径）")
    q.add_argument("--budget", type=int, default=None, help="限制检索 token 预算")
    q.add_argument(
        "--synthesize",
        action="store_true",
        help="用本地模型把检索到的子图综述成一段答案",
    )
    q.add_argument(
        "--model",
        default=os.environ.get("OLLAMA_MODEL", "glm-4.7-flash:latest"),
        help="综述用的本地模型",
    )
    q.add_argument("--ollama-base", default=None, help="覆盖 OLLAMA_BASE_URL")
    q.set_defaults(func=cmd_query)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
