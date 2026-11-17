FROM python:3.12-slim

# 让 print 立即输出到日志（Render 上排查问题必需）
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# 先装依赖，利用镜像层缓存：只改代码时不会重装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 云平台（Render/Railway）会注入 PORT；Hugging Face Spaces 固定 7860
ENV PORT=7860
EXPOSE 7860

# 用 shell 形式，确保能读到运行时的 $PORT
CMD ["sh", "-c", "python run_web.py --no-open --bundle data/demo_xuhui.bundle --host 0.0.0.0 --port ${PORT:-7860}"]
