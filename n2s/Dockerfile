FROM python:3.12-slim

WORKDIR /app

# 依赖（含 imageio-ffmpeg：自带静态 ffmpeg 二进制，免去 apt 装 ffmpeg 的重依赖）
COPY requirements.txt .
# 加长超时 + 重试，容忍网络抖动
RUN pip install --no-cache-dir --timeout 120 --retries 5 -r requirements.txt

COPY app ./app
COPY static ./static

# 数据目录（部署时挂载为卷）
RUN mkdir -p /app/data/notes /app/data/audio_cache

# 非 root 用户
RUN useradd -m n2s
RUN chown -R n2s:n2s /app/data
USER n2s

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
