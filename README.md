# sysmap-local

把「调用浏览器分析已登录系统整体架构 → 知识图谱」这个能力**完全本地化**。
不依赖云端 Claude/GPT，用本地模型（Ollama 上的 GLM / Qwen 等）就能跑，质量几乎不掉点。

产出 6 张图并融合成一张可查询的知识图谱：
1. 功能地图（Feature map）2. 路由地图（Route map）3. API 地图 4. 用户权限地图
5. 管理功能地图（Admin map）6. 文件处理功能地图（File-handling map）

---

## 方案：为什么本地也能 100%

整条流水线拆成两段，**只有第二段的一小部分用到模型**：

```
你已登录的 Chrome
       │ CDP 只读（browser-harness，本地）
       ▼
[A] crawl.py ── 纯代码，无 LLM ──► <out>/raw/*.md
       │   BFS 遍历同源路由 + CDP 抓 XHR/Fetch + 读 DOM 控件
       │   直接把关系写成显式句子：
       │     "Route /x calls API GET /y"
       │     "Feature \"导出\" is available on route /x"
       │     "Route /x was denied access to API ... (permission restriction)"
       ▼
[B] graphify ── 本地 LLM 后端(ollama) ──► graph.json + graph.html + GRAPH_REPORT.md
       ├─ extract：AST(确定性) + 语义补边/去重（本地模型）
       └─ cluster-only：社区检测(确定性) + 社区命名(本地模型) + 报告/HTML
```

**关键洞察**：最难、最影响质量的「侦察」(A) 是确定性代码，零模型参与；6 张图的关系
已经被代码写成显式英文句子。留给模型 (B) 的只是「把已显式的关系连成图、给社区起名、
回答时综述子图」——这些任务即便是 7B~30B 的本地模型也能稳定胜任。所以：

- **本地化 ≠ 降级**：图的骨架来自代码，不来自模型。
- **可复现**：编排是确定性脚本，没有云端 agent 的随机性。
- **零数据外泄**：登录态系统的 DOM/网络流量只在本机处理。

### 现成项目情况
- `browser-harness`（你已装）→ 复用为只读 CDP 侦察器，**本身就是本地的**，无需替换。
- `graphify`（你已装，`uv tool`）→ **已内置 `ollama` 后端**（还有 openai/deepseek/
  gemini/claude-cli/azure/bedrock）。本地化主要是「编排 + 配置」，不是重写。
- 本仓库新增的 `sysmap_local.py` = 替换掉原本由云端 Claude 充当的「编排 agent」，
  改为确定性 Python，把 A→B 串起来并默认走本地 Ollama。

---

## 依赖

| 组件 | 作用 | 你的机器 |
|---|---|---|
| `browser-harness` | 只读 CDP 控制你已登录的 Chrome | 已装（$PATH） |
| `graphify` | 构图/聚类/查询，内置 ollama 后端 | 已装（`~/.local/bin/graphify`） |
| `ollama` + 一个本地模型 | 语义补边 / 社区命名 / 查询综述 | 已装；模型 `glm-4.7-flash:latest` |

> 想换更专精代码的小模型：`ollama pull qwen2.5-coder:7b`，再用 `--model qwen2.5-coder:7b`。

---

## 安装

```bash
# 1) 克隆本仓库
git clone https://github.com/1lkla/sysmap.git
cd sysmap

# 2) 安装 graphify（构图/聚类/查询，内置 ollama 后端）
uv tool install graphifyy          # 推荐；或 pip install graphifyy

# 3) 安装 browser-harness（只读 CDP 控制你已登录的 Chrome）
#    见 https://github.com/<browser-harness> 或你本地的 browser-harness/install.md
#    确认它在 $PATH 上：
which browser-harness

# 4) 安装 Ollama + 拉一个本地模型
brew install ollama                 # 或装 Ollama.app
ollama serve &
ollama pull glm-4.7-flash           # 默认模型；或 qwen2.5-coder:7b

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
- `--model NAME` 本地模型名（默认 `glm-4.7-flash:latest`）
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
