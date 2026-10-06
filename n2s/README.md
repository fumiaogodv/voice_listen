# N2S — Note-to-Speech

把编号知识点笔记变成"可连播的听书"：丢文件 → 自动转 MP3 → 网页听，带歌词式文字跟随 + 视频式进度条 + 断点续播。

## 本地开发

环境要求：Python 3.12+。

> ffmpeg 不强制安装：程序优先用系统 ffmpeg，没有则自动回退到 `imageio-ffmpeg`（随 pip 安装，自带静态二进制）。

```bash
pip install -r requirements.txt
# 把测试笔记复制进 notes 目录
cp sample/*.md data/notes/
uvicorn app.main:app --reload
```

打开 http://127.0.0.1:8000 。

## 部署（N100 + Docker）

```bash
docker compose up -d --build
```

反向代理见 `Caddyfile`（公网务必加 Basic Auth）。

> 镜像内已通过 `imageio-ffmpeg` 自带 ffmpeg，无需在 N100 上另装 ffmpeg。

## 文档

| 文档 | 说明 |
|---|---|
| `笔记序号规范.md` | 笔记怎么写才能正确分条、读对编号（必读） |
| `文件放置说明.md` | 笔记放哪里、分类目录怎么建 |

## 目录结构

```
app/           后端（FastAPI + edge-tts + SQLite）
  main.py      路由 + 静态挂载 + 生命周期
  config.py    全部可调配置
  db.py        SQLite 访问层
  scanner.py   目录扫描 + 生成队列
  textproc.py  分条/编号转写/Markdown 清洗
  tts.py       edge-tts 封装
  pipeline.py  生成管线（分条→TTS→拼接→写库）
static/        前端（单页，无框架）
data/          运行时数据（notes / audio_cache / n2s.db）
sample/        示例笔记
```

## 使用方式

1. 把 `.md` / `.txt` 文件丢进 `data/notes/`（可用子目录做分类，支持任意层级）
2. 程序自动扫描并后台转成 MP3（列表显示"转换中…"）
3. 点文件即播放，支持 ±10s、倍速、拖进度、自动连播
4. 编号默认读作"第一条、第二条"，可在 `config.py` 里关闭
