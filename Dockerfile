FROM python:3.10-slim-bookworm

WORKDIR /app

# 配置apt镜像源
RUN rm -rf /etc/apt/sources.list.d/* && \
    rm -f /etc/apt/sources.list && \
    echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm main contrib non-free non-free-firmware" > /etc/apt/sources.list && \
    echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm-updates main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
    echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm-backports main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
    echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian-security bookworm-security main contrib non-free non-free-firmware" >> /etc/apt/sources.list

# 安装系统依赖
RUN apt-get update && \
    apt-get install -y \
    curl \
    ffmpeg \
    aria2 \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    libqt5gui5 \
    libqt5widgets5 \
    libqt5core5a \
    && rm -rf /var/lib/apt/lists/*

# 设置环境变量以支持无头Qt
ENV QT_QPA_PLATFORM=offscreen

# 先复制依赖文件并安装
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制应用代码
COPY . .

# 创建必要的目录
RUN mkdir -p AppData/cache AppData/logs AppData/models work-dir && \
    chmod -R 777 AppData work-dir

# 设置环境变量
ARG OPENAI_BASE_URL
ARG OPENAI_API_KEY
ENV OPENAI_BASE_URL=${OPENAI_BASE_URL}
ENV OPENAI_API_KEY=${OPENAI_API_KEY}

# 启动应用
CMD ["python", "main.py"]