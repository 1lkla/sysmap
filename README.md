# sysmap-local

**中文** · [English](./README.en.md)

把「调用浏览器分析已登录系统整体架构 → 知识图谱」这个能力**完全本地化**。
不依赖云端 Claude/GPT，用本地模型（Ollama 上的 GLM / Qwen 等）就能跑，质量几乎不掉点。

产出 6 张图并融合成一张可查询的知识图谱：
1. 功能地图（Feature map）2. 路由地图（Route map）3. API 地图 4. 用户权限地图
5. 管理功能地图（Admin map）6. 文件处理功能地图（File-handling map）

---

## 方案：为什么本地也能 100%

**图谱的结构（节点 + 边）完全由代码确定性生成，不经过任何模型**。模型只用于两件
可选的事：给社区起个名字、查询时把子图综述成一段话。

```
你已登录的 Chrome
       │ CDP 只读（browser-harness，本地）
       ▼
[A] crawl.py ── 纯代码，无 LLM ──►  <out>/raw/*.md   (6 张人读地图)
       │                          +  graphify-out/graph.json (确定性图谱)
       │   1) 解析所有同源 JS 业务包：抠出 SPA 路由表 + /api 端点(含方法)
       │   2) 用发现的路由逐个 GET 导航，CDP 抓运行时 XHR/Fetch + 401/403 + DOM 控件
       │   3) 把 路由/API/功能/权限/管理/文件 直接组装成 graph.json
       ▼
[B] graphify cluster-only ──► 社区检测(确定性) + 社区命名(本地模型, 可选) + 报告 + HTML
```

**关键洞察**：sysmap 的六张地图本来就是结构化的，所以图谱直接由代码组装——**没有 LLM
抽取这一步**，也就没有「模型把长列表压缩掉」的损失。这意味着：

- **本地图谱 = 云端图谱**：结构由代码生成，与用什么模型无关，27 个 API、11 条路由
  一个不少。模型只决定社区名好不好听。
- **侦察更深**：不止跟 `<a>` 链接，还静态解析 JS 业务包，挖出 SPA 路由和接口
  （登录/上传/查询/缺陷/用户管理…），并逐路由驱动运行时抓包记录真实 401/403。
- **可复现 / 零数据外泄**：确定性脚本无随机性；登录态系统的数据只在本机处理。

### 现成项目情况
- `browser-harness`（你已装）→ 复用为只读 CDP 侦察器，**本身就是本地的**，无需替换。
- `graphify`（你已装，`uv tool`）→ **已内置 `ollama` 后端**（还有 openai/deepseek/
  gemini/claude-cli/azure/bedrock）。本地化主要是「编排 + 配置」，不是重写。
- 本仓库新增的 `sysmap_local.py` = 替换掉原本由云端 Claude 充当的「编排 agent」，
  改为确定性 Python，把 A→B 串起来并默认走本地 Ollama。

---

## 为什么图谱构建去掉了 LLM（靶场实测促成）

早期版本用 LLM 从地图里「抽取」图谱，靶场实测暴露了它的不可靠——**同一份地图、只换
后端**：

| 构图方式 | 节点 | 边 | 结果 |
|---|---|---|---|
| LLM 抽取 · 通用对话模型 glm-4.7-flash | 6 | **0** | ❌ 把每个文件压成巨型节点，关系全丢 |
| LLM 抽取 · 代码模型 qwen2.5-coder:7b | 11→7 | 16→6 | ⚠️ 小输入尚可，**大输入(27 API)会被压缩** |
| LLM 抽取 · 云端 Claude | 12 | 17 | ✅ 好，但仍随模型波动、且非本地 |
| **确定性组装（现方案）** | **61** | **93** | ✅ 与地图一一对应，27 API/11 路由一个不少 |

结论：地图已是结构化数据，再让模型"抽取"只会引入压缩/幻觉/随机性。现在 `crawl.py`
**直接组装 graph.json**，图谱结构不再依赖模型——本地与云端产出完全一致。模型（默认
`qwen2.5-coder:7b`）只用于**社区命名**和**查询综述**，不在线也能出完整图谱（社区名退化
为 `Community N`）。

---

## 依赖

| 组件 | 作用 | 必需性 |
|---|---|---|
| [`browser-harness`](https://github.com/browser-use/browser-harness) | 只读 CDP 控制你已登录的 Chrome | **必需** |
| `graphify` + `[ollama]` extra | 聚类/报告/HTML/查询（图谱本体由 crawl.py 直接生成） | **必需** |
| `ollama` + 一个本地模型 | 仅用于**社区命名 + 查询综述**（图谱结构不依赖它） | 可选 |

> 图谱的节点和边是确定性生成的，**Ollama 不在线也能产出完整图谱**（社区名退化为
> `Community N`）。要社区命名/综述时，默认模型 `qwen2.5-coder:7b`。

---

## 安装

```bash
# 1) 克隆本仓库
git clone https://github.com/1lkla/sysmap.git
cd sysmap

# 2) 安装 graphify（务必带 [ollama] extra，否则 ollama 后端报缺 openai 包）
uv tool install "graphifyy[ollama]"   # 推荐；或 pip install "graphifyy[ollama]"

# 3) 安装 browser-harness（只读 CDP 控制你已登录的 Chrome）
#    https://github.com/browser-use/browser-harness （见其 install.md）
#    安装后确认它在 $PATH 上：
which browser-harness

# 4) 安装 Ollama + 拉默认的代码/抽取模型
brew install ollama                 # 或装 Ollama.app
ollama serve &
ollama pull qwen2.5-coder:7b       # 默认模型（代码/结构化抽取，实测追平云端 Claude）

# 5) 自检：确认三件套就绪
which graphify browser-harness ollama
```

无需额外 Python 依赖——编排器只用标准库（`urllib`/`subprocess`/`argparse`）。
Python 3.9+ 即可。

---

## 用法

```bash
# 0) 确保 Ollama 在线（Ollama.app 或）
ollama serve &

# 1) 在你自己的 Chrome 里登录目标系统，停在一个内容页

# 2) 构建图谱（只读侦察 → 本地构图）
python3 sysmap_local.py build https://your-app/dashboard --max 60
#   或：./run.sh build https://your-app/dashboard --max 60

# 3) 向图谱提问（纯图检索）
python3 sysmap_local.py query "哪些路由调用了文件处理 API?"

# 3b) 让本地模型把检索到的子图综述成一段话
python3 sysmap_local.py query "管理后台有哪些功能只有 admin 能用?" --synthesize
```

构建产物在 `./sysmap-out/raw/graphify-out/`：
- `graph.html` —— 浏览器打开的交互式知识图谱
- `GRAPH_REPORT.md` —— God Nodes / 跨社区连接 / 建议问题 的审计报告
- `graph.json` —— GraphRAG 可用的原始图数据
- `../network.jsonl` —— 原始网络抓包（参考）

### 常用参数
- `--max N` 抓取路由上限（默认 40）
- `--out DIR` 输出目录（默认 `./sysmap-out`）
- `--backend NAME` 切换 graphify 后端：`ollama`(默认)/`openai`/`deepseek`/`gemini`/`claude-cli`
- `--model NAME` 本地模型名（默认 `qwen2.5-coder:7b`）
- `--ollama-base URL` 覆盖 `OLLAMA_BASE_URL`（如指到 LM Studio 的 OpenAI 兼容端口）

### 接 LM Studio 而不是 Ollama
LM Studio 提供 OpenAI 兼容端点（默认 `http://localhost:1234/v1`）。两种接法：
```bash
# 仍用 ollama 后端、但把 base 指过去（最省事）
python3 sysmap_local.py build <url> --ollama-base http://localhost:1234/v1 --model <lmstudio-model>
# 或用 openai 后端
OPENAI_BASE_URL=http://localhost:1234/v1 OPENAI_API_KEY=lm-studio \
  python3 sysmap_local.py build <url> --backend openai --model <lmstudio-model>
```

---

## 安全
- 侦察是**只读**的：只做 GET 导航 + 读 DOM，绝不点击 删除/提交/保存 等改状态控件。
- 只对你**拥有或已获授权**评估的系统运行。
- 撞到登录墙会停止并提示，**不会**输入任何凭据。

---

## 文件
- `crawl.py` —— 只读侦察器（产出 6 张图的显式关系 markdown）
- `sysmap_local.py` —— 确定性编排器（替代云端 agent）
- `run.sh` —— 便捷入口
