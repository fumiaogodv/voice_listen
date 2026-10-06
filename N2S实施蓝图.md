# N2S 实施蓝图（需求导向 · Vibecoding 版）

> 用途：你（需求方）不写代码，把本文档按里程碑逐段交给 AI 编码助手执行。每个里程碑都附带**你能在浏览器里亲手验收的标准**——验收通过再进入下一个。
> 已锁定的决策：**TTS 用 edge-tts**；需要**文字展示（歌词式）**与**文件级进度（视频进度条式）**。

---

## 0. 这份文档怎么用（vibecoding 工作流）

1. **一次一个里程碑**。把「第 6 节的对应里程碑全文 + 本文档第 2~5 节作为上下文」发给 AI，要求它一次产出完整可运行的代码。
2. **按验收标准逐条检查**。验收不通过就把现象（截图/报错）贴回给 AI 修，不要自己改代码。
3. **不要跳里程碑**。M2 的音频时间戳表是 M4 文字同步的地基，顺序不能乱。
4. 所有里程碑完成后，按第 7 节整体验收，再用第 8 节部署到 N100。

---

## 1. 需求冻结（最终形态）

**一句话**：把编号知识点文件变成"可连播的听书"，像音乐播放器一样有歌词（文字跟随高亮）、像视频播放器一样有进度条和断点续播。

### 必须有（M1–M6 范围）

- [ ] 手动把 `.md`/`.txt` 文件丢进 `notes/` 目录，程序自动捕获并转换
- [ ] 点一个文件即开始播放（缓存秒开），顺序自动连播同目录下一个文件
- [ ] 播放控制：播放/暂停、±10 秒、倍速 1.0/1.25/1.5/2.0x
- [ ] 视频式进度条：可拖动、显示已播/总时长、缓冲正常
- [ ] 歌词式文字展示：当前朗读到的知识点**高亮 + 自动滚动**，点任意一条跳转到对应音频位置
- [ ] 断点续播：关掉页面（或换设备）再打开，自动定位到上次位置
- [ ] 左侧文件列表带进度标识（未开始 / 已听 xx% / 已听完）

### 暂不做（明确排除，避免 AI 发挥）

- 用户系统、多用户、鉴权（鉴权放反向代理层，见第 8 节）
- 在线编辑笔记、上传界面（就是手动丢文件）
- 逐字高亮（只做到"条"级别，不做字级卡拉OK）
- 搜索、收藏、播放列表自定义

---

## 2. 技术栈（定死，不给 AI 选择空间）

| 层 | 选型 | 说明 |
|---|---|---|
| 后端语言 | **Python 3.12** | 全项目唯一编程语言 |
| Web 框架 | FastAPI + uvicorn | 挂静态资源、API、音频流 |
| TTS | **edge-tts**（`pip install edge-tts`） | 音色默认 `zh-CN-XiaoxiaoNeural`，写入配置可改（如 `zh-CN-YunxiNeural` 男声） |
| 音频处理 | ffmpeg（拼接、插静音、探测时长） | 系统级依赖，非 pip |
| 数据库 | SQLite（标准库 `sqlite3`，**不引入 ORM**） | 单文件 `n2s.db` |
| 前端 | **单个 `index.html` + 原生 JS + CSS，无框架无构建** | 不用 Vue/React/npm |
| 部署 | Docker + docker-compose + 反向代理 | 见第 8 节 |

依赖清单（`requirements.txt`）只有三行级别：`fastapi`、`uvicorn[standard]`、`edge-tts`。

---

## 3. 核心设计（决定成败的三个机制）

### 3.1 缓存键 = 文件内容 hash

以**全文 sha256** 作为缓存键，而非 mtime（编辑器可能只 touch 不改内容）。文件内容不变 → 永不重新生成；内容变了 → 音频重生成，进度**重置**（知识点变了，旧位置无意义）。

### 3.2 分条生成 + 时间戳映射表（文字同步的地基）

这是整个项目最关键的设计。**必须按条生成，再拼接成一个 MP3，并记录每条的起止秒数**：

```
第 1 条文本 ──edge-tts──> seg_000.mp3 ┐
第 2 条文本 ──edge-tts──> seg_001.mp3 ┤──ffmpeg 拼接（条间插 0.6s 静音）──> 整文件 audio.mp3
  ...                                  ┘
同时记录：第 N 条 → [start_sec, end_sec] 写入 segments 表
```

前端拿到 `segments` 表后，`timeupdate` 事件里查当前秒落在哪条 → 高亮 + 滚动 + 点击行 seek。**歌词效果的精度取决于这张表，所以起止秒必须来自生成时的真实数据（ffprobe 探测），不能估算。**

### 3.3 文本预处理规则（听感的关键，需求方会亲耳验收）

1. **分条**：按行解析，`^\s*\d+[.、)．]\s*` 开头为新条；不以编号开头的行**并入上一条**（如示例中"IO逻辑实现设备控制功能"是第 5 条的补充）；首行无编号则自成一条。
2. **编号转写**：`1.` → `第一点。`，`2.` → `第二点。`……（中文序数；`10` 起读"第十点""第十一点"）。可配置开关。
3. **Markdown 清洗**：去掉 `**`、`*`、`` ` ``、`#`、`[]()` 等；代码块/表格若出现，整块**跳过不读**（本项目内容基本没有，防御性处理）。
4. **条间停顿**：拼接时每条之间插入 **0.6 秒静音**，否则知识点连读糊成一片。

---

## 4. 数据模型（SQLite 建表语句，直接给 AI）

```sql
CREATE TABLE IF NOT EXISTS files (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  rel_path     TEXT UNIQUE NOT NULL,   -- 相对 notes/ 的路径，如 操作系统/设备管理.md
  title        TEXT NOT NULL,          -- 文件名去扩展名
  category     TEXT NOT NULL,          -- 一级目录名
  content_hash TEXT NOT NULL,          -- 全文 sha256，缓存键
  status       TEXT DEFAULT 'pending', -- pending | generating | ready | failed
  audio_path   TEXT,                   -- audio_cache 下的相对路径
  duration     REAL,                   -- 总秒数
  updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS segments (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  file_id   INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  idx       INTEGER NOT NULL,          -- 第几条（从 0 起）
  text      TEXT NOT NULL,             -- 清洗后的朗读文本（也是前端展示文本）
  start_sec REAL NOT NULL,
  end_sec   REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS progress (
  file_id     INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
  position_sec REAL DEFAULT 0,
  finished    INTEGER DEFAULT 0,
  updated_at  TEXT
);
```

---

## 5. 项目结构与 API

### 5.1 目录结构（AI 按此创建）

```
n2s/
├── app/
│   ├── main.py        # FastAPI 入口：路由、静态挂载、启动时扫描
│   ├── config.py      # NOTES_DIR / CACHE_DIR / DB_PATH / 音色 / 停顿时长 / 编号读法开关
│   ├── db.py          # 建表 + 全部 SQL 访问函数
│   ├── scanner.py     # 扫描 notes/，hash 对比，新增/变更/删除处理
│   ├── textproc.py    # 分条、编号转写、Markdown 清洗（第 3.3 节规则）
│   ├── tts.py         # edge-tts 封装：串行队列、重试（429/超时退避）
│   └── pipeline.py    # 生成管线：分条→逐条 TTS→ffprobe 时长→拼接→写库
├── static/
│   ├── index.html     # 单页应用
│   ├── app.js         # 全部交互逻辑
│   └── style.css
├── data/              # 运行时数据（部署时挂载为卷，不入镜像）
│   ├── notes/         # ← 手动丢文件的地方
│   └── audio_cache/
│   └── n2s.db
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── sample/            # 示例笔记，用于测试
```

### 5.2 API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/library` | 全部分类 → 文件列表（title、status、duration、进度百分比） |
| GET | `/api/files/{id}` | 详情：segments 全量（idx/text/start_sec/end_sec）、audio_url、position_sec |
| POST | `/api/files/{id}/progress` | body: `{position_sec, finished}`，前端定时+暂停+退出时调 |
| POST | `/api/scan` | 手动触发重扫（前端放一个刷新按钮） |
| GET | `/audio/*` | 静态挂载 `audio_cache/`，**必须支持 HTTP Range**（拖进度条的前提；FastAPI/Starlette FileResponse 已支持，验收时确认） |

### 5.3 前端界面（单页三区）

```
┌──────────┬────────────────────────────────┐
│ 左侧栏    │  顶部悬浮播放器（sticky）        │
│ 分类折叠   │  ▶/⏸  −10s +10s  1.0x→2.0x   │
│ 文件列表   │  ━━━━●━━━━━━━━━━ 12:34/45:10  │ ← 视频式进度条
│ ─────────│────────────────────────────────│
│ 未开始    │  文字区（歌词式，大字号疏朗）      │
│ 已听60%  │  第一条知识点……                  │
│ 已听完    │  ▸第二条知识点……（当前高亮+滚动） │
└──────────┴────────────────────────────────┘
```

前端交互规则（给 AI 的硬约束）：

- 播放中每 **4 秒**上报一次进度；`pause`、`pagehide`、`visibilitychange` 时**立即补报**，页面关闭用 `navigator.sendBeacon`（锁屏后定时器会冻结，不补报会丢进度）
- `ended` → 上报 finished=1 → 自动播放同分类下一个未听完文件；全放完则停
- 高亮判定：`timeupdate` 里找 `start_sec <= currentTime < end_sec` 的条目；容器 `scrollIntoView({block:'center'})` 平滑滚动
- 首次播放必须由点击触发（iOS 限制），断点续播做成"自动 seek 到位 + 显示一个大的播放按钮"

---

## 6. 里程碑与验收标准（逐个投喂给 AI）

> 每个里程碑给 AI 的提示词模板：
> "请根据以下实施蓝图实现【Mx】：〔粘贴 Mx 全文〕。技术约束：Python 3.12 + FastAPI + edge-tts + SQLite，前端单 HTML 无框架。请给出完整可运行代码和我要执行的命令。"
> （首次对话时把本文档第 2~5 节一并发给它作为全局上下文。）

### M0 环境骨架（半天内）

- 产出：项目目录、`requirements.txt`、`config.py`、空的 FastAPI 应用，`/api/library` 返回空列表；`sample/` 里放 3 个测试笔记（含示例文件那种编号格式，其中一条故意不带编号）
- 你要跑的命令：`pip install -r requirements.txt` → `uvicorn app.main:app --reload`
- ✅ 验收：浏览器打开 `http://127.0.0.1:8000` 出现空白页面；`/api/library` 返回 `[]`；ffmpeg、edge-tts 均安装可用（`edge-tts --list-voices | findstr Xiao`）

### M1 扫描与入库

- 产出：`scanner.py` + `db.py`；启动扫描 + 每 30 秒轮询 + `/api/scan`
- ✅ 验收：把 sample 文件丢进 `notes/` → 30 秒内 `/api/library` 出现该文件，状态 pending；改一个字 → hash 变化、标记重新生成；删文件 → 列表消失且无报错

### M2 生成管线（核心，允许最长的验收时间）

- 产出：`textproc.py` + `tts.py` + `pipeline.py`
- ✅ 验收（这步要亲耳听）：
  1. 新文件入库后状态流转 pending → generating → ready，`audio_cache/` 出现一个 MP3
  2. `segments` 表条数 = 知识点条数，start/end 秒单调递增
  3. **听 MP3**：编号读作"第一点"而非"1"；条与条之间有明显停顿；`**` 不被读出；不带编号的行被并入上一条朗读
  4. 同时转 5 个文件不崩（串行队列、生成中状态可见）

### M3 播放器

- 产出：`index.html`/`app.js`/`style.css` 的播放部分
- ✅ 验收：点文件秒开播放；倍速切换立即生效且不变调；±10 秒正常；进度条可拖（Range 生效的标志）；一个文件播完自动连播下一个；左侧列表出现进度标识

### M4 歌词式文字同步

- 产出：文字区渲染 + 高亮滚动 + 点击 seek
- ✅ 验收：高亮切换与朗读对齐（耳朵验证，误差应 < 0.5 秒）；点第 5 条跳到第 5 条音频位置；页面不动时文字自动居中滚动；手机浏览器不出现横向滚动条

### M5 断点续播与进度持久化

- 产出：进度上报（定时 + pause + sendBeacon）、重进页面自动定位
- ✅ 验收：听到一半关页面 → 重开自动定位（首次需点一下播放，iOS 规则）；手机锁屏 1 分钟再解锁，进度不回退；两个设备先后打开同一文件，以最后操作为准；全部条目听完 → 列表标记"已听完"

### M6 Docker 化与部署

- 产出：`Dockerfile`（python:3.12-slim + ffmpeg，非 root 用户）、`docker-compose.yml`（挂载 data 卷，端口绑 127.0.0.1）
- ✅ 验收：`docker compose up -d` 后全部功能正常；重启容器，进度与缓存不丢

---

## 7. 整体验收清单（上线前过一遍）

- [ ] 冷启动（空目录）→ 丢文件 → 全自动到可听，无需手工干预
- [ ] 10000 字级别文件生成成功（长文分条无遗漏）
- [ ] edge-tts 断网/限流时：状态标 failed、不崩队列、恢复后可重试（提供 `/api/scan` 重扫入口）
- [ ] 中文文件名、带空格文件名可正常播放（URL 编码）
- [ ] 手机 Safari/微信内置浏览器可用
- [ ] 2.0x 连续听 10 分钟无卡顿、进度准确

---

## 8. 部署（N100 + Docker + 反代）

```yaml
services:
  n2s:
    build: .
    volumes:
      - ./data/notes:/app/data/notes:ro
      - ./data/audio_cache:/app/data/audio_cache
      - ./data/n2s.db:/app/data/n2s.db
    ports:
      - "127.0.0.1:8000:8000"
    restart: unless-stopped
```

反向代理（Caddy，自动 HTTPS + Basic Auth——**公网必须加鉴权**，否则笔记全世界可读）：

```
n2s.你的域名.com {
    basicauth { 用户名 <bcrypt哈希> }
    reverse_proxy 127.0.0.1:8000
}
```

磁盘预估：1 万字 ≈ 30–60 分钟 MP3 ≈ 15–30MB（64kbps 单声道），按你的笔记量级评估 `audio_cache` 所在卷大小。

---

## 9. 已知风险与对策（发给 AI 时一并作为约束）

1. **edge-tts 是非官方接口**：所有生成走串行队列 + 退避重试；失败标 `failed`，不允许静默吞掉；缓存只增不删。
2. **iOS 自动播放限制**：所有自动续播的场景，音频恢复都视为"首次播放"处理。
3. **锁屏定时器冻结**：进度上报依赖事件（pause/pagehide/visibilitychange）+ sendBeacon，不能只靠 setInterval。
4. **进度条拖动**：依赖 HTTP Range；若拖动后音频从头播，说明 Range 没生效，让 AI 修静态文件响应。
5. **编号读法**：默认中文序数（"第一点"），做成 `config.py` 开关，验收不满意可一键切回原样。
