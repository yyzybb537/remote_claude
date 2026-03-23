#!/bin/bash

# 脚本目录（全局变量）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# 颜色定义
RED=$'\033[0;31m'
GREEN=$'\033[0;32m'
YELLOW=$'\033[1;33m'
NC=$'\033[0m' # No Color

# 末尾汇总警告
WARNINGS=()

# 打印函数
print_info() {
    echo -e "${GREEN}ℹ${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_header() {
    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}$1${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

# 确保 ~/.local/bin 在 PATH 中
setup_path() {
    local PROFILE="$HOME/.bash_profile"
    # 不存在则创建
    [[ -f "$PROFILE" ]] || touch "$PROFILE"

    # 未写入 source .bashrc 则追加
    if ! grep -qF '.bashrc' "$PROFILE" 2>/dev/null; then
        echo '[ -f "$HOME/.bashrc" ] && . "$HOME/.bashrc"' >> "$PROFILE"
    fi

    # 未写入则追加
    if ! grep -qF '$HOME/.local/bin' "$PROFILE" 2>/dev/null; then
        echo "" >> "$PROFILE"
        echo '# remote-claude: 确保 ~/.local/bin 在 PATH' >> "$PROFILE"
        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$PROFILE"
    fi

    # 使当前脚本会话立即生效
    source "$PROFILE" 2>/dev/null || true
    export PATH="$HOME/.local/bin:$PATH"
}

# 检查操作系统
check_os() {
    print_header "检查系统环境"

    OS=$(uname -s)
    if [[ "$OS" != "Darwin" && "$OS" != "Linux" ]]; then
        print_error "不支持的操作系统: $OS"
        print_error "Remote Claude 仅支持 macOS 和 Linux"
        exit 1
    fi

    print_success "操作系统: $OS"
}

# 检查 uv
check_uv() {
    print_header "检查 uv"

    if command -v uv &> /dev/null; then
        UV_VERSION=$(uv --version)
        print_success "$UV_VERSION 已安装"
        return
    fi

    print_warning "未找到 uv，正在安装..."

    # 检测可用的 pip 命令
    local PIP_CMD=""
    if command -v pip3 &> /dev/null; then
        PIP_CMD="pip3"
    elif command -v pip &> /dev/null; then
        PIP_CMD="pip"
    fi

    # 方式一：官方安装脚本（需访问 astral.sh/GitHub）
    if curl -LsSf --connect-timeout 10 https://astral.sh/uv/install.sh | sh 2>/dev/null; then
        export PATH="$HOME/.local/bin:$PATH"
    fi

    # 方式二：pip + PyPI（GitHub 访问受限时首选；国内镜像比 GitHub 稳定）
    if ! command -v uv &> /dev/null && [[ -n "$PIP_CMD" ]]; then
        print_warning "尝试 pip 安装 uv（官方 PyPI）..."
        ($PIP_CMD install uv --quiet 2>/dev/null || \
         $PIP_CMD install uv --quiet --break-system-packages 2>/dev/null) && \
            export PATH="$HOME/.local/bin:$PATH"
    fi

    # 方式三：pip + 国内镜像（清华 PyPI，适合无法访问 GitHub/pypi.org 的内网环境）
    if ! command -v uv &> /dev/null && [[ -n "$PIP_CMD" ]]; then
        print_warning "尝试 pip 安装 uv（清华镜像）..."
        ($PIP_CMD install uv --quiet \
            -i https://pypi.tuna.tsinghua.edu.cn/simple/ \
            --trusted-host pypi.tuna.tsinghua.edu.cn 2>/dev/null || \
         $PIP_CMD install uv --quiet \
            -i https://pypi.tuna.tsinghua.edu.cn/simple/ \
            --trusted-host pypi.tuna.tsinghua.edu.cn \
            --break-system-packages 2>/dev/null) && \
            export PATH="$HOME/.local/bin:$PATH"
    fi

    # 方式四：conda/mamba（适合已有 Anaconda/Miniconda 环境的机器）
    if ! command -v uv &> /dev/null; then
        if command -v mamba &> /dev/null; then
            print_warning "尝试 mamba 安装 uv..."
            mamba install -c conda-forge uv -y --quiet 2>/dev/null || true
        elif command -v conda &> /dev/null; then
            print_warning "尝试 conda 安装 uv..."
            conda install -c conda-forge uv -y --quiet 2>/dev/null || true
        fi
    fi

    # 方式五：brew（macOS 备用）
    if ! command -v uv &> /dev/null && [[ "$OS" == "Darwin" ]] && command -v brew &> /dev/null; then
        print_warning "尝试 brew install uv..."
        brew install uv 2>/dev/null || true
    fi

    if command -v uv &> /dev/null; then
        print_success "uv 安装成功"

        # 确保 ~/.local/bin 写入 shell rc（uv 官方脚本可能写 .zprofile 而非 .zshrc）
        local _RC
        if [[ -n "$ZSH_VERSION" ]] || [[ "$(basename "$SHELL")" == "zsh" ]]; then
            _RC="$HOME/.zshrc"
        else
            _RC="$HOME/.bashrc"
        fi
        if ! grep -qF "$HOME/.local/bin" "$_RC" 2>/dev/null; then
            echo "" >> "$_RC"
            echo "# uv" >> "$_RC"
            echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$_RC"
            print_success "已将 \$HOME/.local/bin 写入 $_RC"
        fi
    else
        print_error "uv 安装失败，请手动安装，可选方式："
        print_info "  pip3 install uv"
        print_info "  pip3 install uv -i https://pypi.tuna.tsinghua.edu.cn/simple/"
        print_info "  conda install -c conda-forge uv"
        print_info "  详见: https://docs.astral.sh/uv/getting-started/installation/"
        exit 1
    fi
}

# 检查并安装 tmux（要求 3.6+）
check_tmux() {
    print_header "检查 tmux"

    # CI 模式：跳过 tmux 版本检查（Docker 环境可能没有 sudo）
    if [ "$CI_MODE" = "true" ]; then
        if command -v tmux &> /dev/null; then
            TMUX_VERSION=$(tmux -V)
            print_success "$TMUX_VERSION 已安装（CI 模式跳过版本检查）"
            return
        else
            print_error "未找到 tmux"
            WARNINGS+=("tmux 未安装，CI 模式跳过版本检查")
            return
        fi
    fi

    REQUIRED_MAJOR=3
    REQUIRED_MINOR=6

    install_tmux() {
        if [[ "$OS" == "Darwin" ]]; then
            if ! command -v brew &> /dev/null; then
                print_warning "未找到 Homebrew，正在自动安装..."
                /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
                # 将 Homebrew 加入 PATH（Apple Silicon / Intel 路径不同）
                if [[ -x "/opt/homebrew/bin/brew" ]]; then
                    eval "$(/opt/homebrew/bin/brew shellenv)"
                elif [[ -x "/usr/local/bin/brew" ]]; then
                    eval "$(/usr/local/bin/brew shellenv)"
                fi
                if ! command -v brew &> /dev/null; then
                    print_error "Homebrew 安装失败，请手动安装后重试: https://brew.sh"
                    exit 1
                fi
                print_success "Homebrew 安装成功"
            fi
            brew install tmux 2>/dev/null || true
        elif [[ "$OS" == "Linux" ]]; then
            if command -v apt-get &> /dev/null; then
                sudo apt-get update && sudo apt-get install -y tmux || true
            elif command -v yum &> /dev/null; then
                sudo yum install -y tmux || true
            elif command -v pacman &> /dev/null; then
                sudo pacman -Sy --noconfirm tmux || true
            elif command -v apk &> /dev/null; then
                sudo apk add --no-cache tmux || true
            elif command -v zypper &> /dev/null; then
                sudo zypper install -y tmux || true
            else
                print_warning "无法识别包管理器，尝试从源码编译 tmux..."
                install_tmux_from_source
                return
            fi
        fi
        print_success "tmux 安装成功"
    }

    install_tmux_from_source() {
        local TMUX_VERSION_TAG="3.6a"
        local TMUX_URL="https://github.com/tmux/tmux/releases/download/${TMUX_VERSION_TAG}/tmux-${TMUX_VERSION_TAG}.tar.gz"

        print_warning "包管理器版本不满足要求，尝试从源码编译 tmux ${TMUX_VERSION_TAG}..."

        # 安装编译依赖
        if [[ "$OS" == "Darwin" ]]; then
            brew install libevent ncurses pkg-config bison 2>/dev/null || true
        elif command -v apt-get &> /dev/null; then
            sudo apt-get install -y build-essential libevent-dev libncurses5-dev libncursesw5-dev bison pkg-config || true
        elif command -v yum &> /dev/null; then
            sudo yum groupinstall -y "Development Tools" || true
            sudo yum install -y libevent-devel ncurses-devel bison || true
        fi

        # 确定安装前缀
        local PREFIX="/usr/local"
        if ! sudo -n true 2>/dev/null; then
            print_warning "无 sudo 权限，将安装到 \$HOME/.local"
            PREFIX="$HOME/.local"
        fi

        # 创建临时目录，编译完成后清理
        local TMPDIR
        TMPDIR=$(mktemp -d)
        trap "rm -rf '$TMPDIR'" RETURN

        print_warning "下载 tmux-${TMUX_VERSION_TAG}.tar.gz..."
        if ! curl -fsSL "$TMUX_URL" -o "$TMPDIR/tmux.tar.gz"; then
            print_warning "下载失败，请检查网络或手动安装 tmux ${REQUIRED_MAJOR}.${REQUIRED_MINOR}+"
            WARNINGS+=("tmux 源码下载失败，请手动安装 tmux ${REQUIRED_MAJOR}.${REQUIRED_MINOR}+")
            return
        fi

        tar -xzf "$TMPDIR/tmux.tar.gz" -C "$TMPDIR"
        local SRC_DIR
        SRC_DIR=$(find "$TMPDIR" -maxdepth 1 -type d -name "tmux-*" | head -1)

        print_warning "编译 tmux（可能需要几分钟）..."
        if ! (cd "$SRC_DIR" && ./configure --prefix="$PREFIX" && make -j"$(nproc 2>/dev/null || echo 2)"); then
            print_warning "编译失败，请手动安装 tmux ${REQUIRED_MAJOR}.${REQUIRED_MINOR}+"
            WARNINGS+=("tmux 源码编译失败，请手动安装 tmux ${REQUIRED_MAJOR}.${REQUIRED_MINOR}+")
            return
        fi

        if [[ "$PREFIX" == "/usr/local" ]]; then
            sudo make -C "$SRC_DIR" install || { WARNINGS+=("tmux make install 失败，请手动安装 tmux ${REQUIRED_MAJOR}.${REQUIRED_MINOR}+"); return; }
        else
            make -C "$SRC_DIR" install || { WARNINGS+=("tmux make install 失败，请手动安装 tmux ${REQUIRED_MAJOR}.${REQUIRED_MINOR}+"); return; }
            # 若 $HOME/.local/bin 不在 PATH 中，自动写入 shell 配置
            if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
                export PATH="$HOME/.local/bin:$PATH"
                local _RC
                if [[ "$(basename "$SHELL")" == "zsh" ]]; then
                    _RC="$HOME/.zshrc"
                else
                    _RC="$HOME/.bashrc"
                fi
                local _PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
                if ! grep -qF "$HOME/.local/bin" "$_RC" 2>/dev/null; then
                    echo "" >> "$_RC"
                    echo "# remote-claude: tmux 路径" >> "$_RC"
                    echo "$_PATH_LINE" >> "$_RC"
                    print_success "已自动将 \$HOME/.local/bin 加入 PATH（写入 $_RC）"
                fi
            fi
        fi

        print_success "tmux ${TMUX_VERSION_TAG} 源码编译安装完成（前缀：${PREFIX}）"
    }

    check_version() {
        # tmux -V 输出格式：tmux 3.6 或 tmux 3.4a
        local ver_str
        ver_str=$(tmux -V | awk '{print $2}')
        local major minor
        major=$(echo "$ver_str" | cut -d. -f1)
        minor=$(echo "$ver_str" | cut -d. -f2 | tr -dc '0-9')
        if [[ "$major" -gt "$REQUIRED_MAJOR" ]] || \
           [[ "$major" -eq "$REQUIRED_MAJOR" && "${minor:-0}" -ge "$REQUIRED_MINOR" ]]; then
            return 0
        fi
        return 1
    }

    if command -v tmux &> /dev/null; then
        TMUX_VERSION=$(tmux -V)
        if check_version; then
            print_success "$TMUX_VERSION 已安装（满足 >= ${REQUIRED_MAJOR}.${REQUIRED_MINOR}）"
            return
        else
            print_warning "$TMUX_VERSION 版本过低，需要 ${REQUIRED_MAJOR}.${REQUIRED_MINOR} 或更高，正在升级..."
            install_tmux
            # 升级后再次验证，版本仍不满足则走源码编译（跨平台）
            if ! check_version; then
                install_tmux_from_source
                if check_version; then
                    print_success "tmux 已升级至 $(tmux -V)"
                else
                    print_warning "源码编译后版本仍不满足要求（$(tmux -V)），需要 ${REQUIRED_MAJOR}.${REQUIRED_MINOR}+"
                    WARNINGS+=("tmux 版本不满足要求（$(tmux -V)），需要 ${REQUIRED_MAJOR}.${REQUIRED_MINOR}+，请手动升级")
                fi
            else
                print_success "tmux 已升级至 $(tmux -V)"
            fi
        fi
    else
        print_warning "未找到 tmux，正在安装..."
        install_tmux
        if ! check_version; then
            install_tmux_from_source
            if ! check_version; then
                print_warning "源码编译后版本仍不满足要求（$(tmux -V)），需要 ${REQUIRED_MAJOR}.${REQUIRED_MINOR}+"
                WARNINGS+=("tmux 版本不满足要求（$(tmux -V)），需要 ${REQUIRED_MAJOR}.${REQUIRED_MINOR}+，请手动升级")
            fi
        fi
    fi
}

# 检查 Claude CLI
check_claude() {
    print_header "检查 Claude CLI"

    if command -v claude &> /dev/null; then
        print_success "Claude CLI 已安装"
        return
    fi

    print_warning "未找到 Claude CLI"
    print_info "请访问 https://claude.ai/code 安装 Claude CLI"

    if $NPM_MODE; then
        print_info "（npm 模式：跳过交互，请安装后重新运行）"
        return
    fi

    read -p "$(echo -e ${YELLOW}是否已安装 Claude CLI？${NC} [y/N]: )" -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_error "请先安装 Claude CLI 后再运行此脚本"
        exit 1
    fi

    if ! command -v claude &> /dev/null; then
        print_error "仍未找到 claude 命令，请检查安装或 PATH 配置"
        exit 1
    fi
}

# 检查 Codex CLI
check_codex() {
    print_header "检查 Codex CLI"

    if command -v codex &> /dev/null; then
        print_success "Codex CLI 已安装"
        return
    fi

    print_warning "未找到 Codex CLI"
    print_info "请运行以下命令安装 Codex CLI："
    print_info "  npm install -g @openai/codex"
    print_info "或访问 https://github.com/openai/codex 了解更多"

    if $NPM_MODE; then
        print_info "（npm 模式：跳过交互，请安装后重新运行）"
        return
    fi
}

# 安装 Python 依赖
install_dependencies() {
    print_header "安装 Python 依赖"

    if [ ! -f "pyproject.toml" ]; then
        print_error "未找到 pyproject.toml 文件"
        exit 1
    fi

    print_info "正在通过 uv 同步依赖..."
    if $NPM_MODE; then
        uv sync || { print_error "依赖安装失败"; exit 1; }
    else
        uv sync || { print_error "依赖安装失败"; exit 1; }
    fi

    print_success "依赖安装完成"

    # 上报 init_install 事件（后台执行，不阻塞，失败静默）
    # 使用 uv run 确保使用项目虚拟环境中的 Python
    uv run --project "$SCRIPT_DIR" python3 scripts/report_install.py &>/dev/null &
}

# 配置飞书环境
configure_lark() {
    print_header "配置飞书客户端"

    ENV_FILE="$HOME/.remote-claude/.env"
    TEMPLATE_ENV="$SCRIPT_DIR/resources/defaults/.env.example"
    mkdir -p "$HOME/.remote-claude"

    # 迁移旧 .env（项目根目录）到新位置
    if [ -f ".env" ] && [ ! -f "$ENV_FILE" ]; then
        mv ".env" "$ENV_FILE"
        print_success "已将 .env 迁移到 $ENV_FILE"
    fi

    if [ -f "$ENV_FILE" ]; then
        print_warning ".env 文件已存在（$ENV_FILE），跳过配置"
        return
    fi

    if [ ! -f "$TEMPLATE_ENV" ]; then
        print_error "未找到 .env.example 模板文件: $TEMPLATE_ENV"
        exit 1
    fi

    read -p "$(echo -e ${YELLOW}是否需要配置飞书客户端？${NC} [y/N]: )" -n 1 -r
    echo

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        cp "$TEMPLATE_ENV" "$ENV_FILE"
        print_success ".env 文件已创建于 $ENV_FILE"
        print_warning "请编辑 $ENV_FILE，填写以下信息："
        print_info "  - FEISHU_APP_ID: 飞书应用的 App ID"
        print_info "  - FEISHU_APP_SECRET: 飞书应用的 App Secret"
        print_info ""
        print_info "获取方式: 登录飞书开放平台 -> 创建应用 -> 凭证与基础信息"
    else
        print_info "跳过飞书配置（可稍后手动配置）"
    fi
}

# 创建必要目录
create_directories() {
    print_header "创建运行目录"

    SOCKET_DIR="/tmp/remote-claude"
    USER_DATA_DIR="$HOME/.remote-claude"

    if [ ! -d "$SOCKET_DIR" ]; then
        mkdir -p "$SOCKET_DIR"
        print_success "创建目录: $SOCKET_DIR"
    else
        print_info "目录已存在: $SOCKET_DIR"
    fi

    if [ ! -d "$USER_DATA_DIR" ]; then
        mkdir -p "$USER_DATA_DIR"
        print_success "创建目录: $USER_DATA_DIR"
    else
        print_info "目录已存在: $USER_DATA_DIR"
    fi
}

# 初始化配置文件
init_config_files() {
    print_header "初始化配置文件"

    local CONFIG_FILE="$USER_DATA_DIR/config.json"
    local RUNTIME_FILE="$USER_DATA_DIR/runtime.json"
    local LEGACY_FILE="$USER_DATA_DIR/lark_group_mapping.json"
    local CONFIG_TEMPLATE="$SCRIPT_DIR/resources/defaults/config.default.json"
    local RUNTIME_TEMPLATE="$SCRIPT_DIR/resources/defaults/runtime.default.json"

    if [ ! -f "$CONFIG_TEMPLATE" ]; then
        print_error "未找到配置模板: $CONFIG_TEMPLATE"
        exit 1
    fi

    if [ ! -f "$RUNTIME_TEMPLATE" ]; then
        print_error "未找到运行时模板: $RUNTIME_TEMPLATE"
        exit 1
    fi

    # 1. 创建默认 config.json（如不存在）
    if [ ! -f "$CONFIG_FILE" ]; then
        cp "$CONFIG_TEMPLATE" "$CONFIG_FILE"
        print_success "创建默认配置: $CONFIG_FILE"
    else
        print_info "配置文件已存在: $CONFIG_FILE"
    fi

    # 2. 创建空的 runtime.json（如不存在）
    if [ ! -f "$RUNTIME_FILE" ]; then
        cp "$RUNTIME_TEMPLATE" "$RUNTIME_FILE"
        print_success "创建运行时配置: $RUNTIME_FILE"
    else
        print_info "运行时配置已存在: $RUNTIME_FILE"
    fi

    # 3. 迁移旧 lark_group_mapping.json
    if [ -f "$LEGACY_FILE" ]; then
        print_info "检测到旧配置文件: $LEGACY_FILE"
        # 使用 jq 解析 JSON 并合并
        if command -v jq &> /dev/null; then
            # 读取旧映射
            local legacy_mappings
            legacy_mappings=$(cat "$LEGACY_FILE" 2>/dev/null)
            # 检查是否为有效 JSON 且非空
            if echo "$legacy_mappings" | jq -e '.' > /dev/null 2>&1; then
                # 合并到 runtime.json（仅当 lark_group_mappings 为空时）
                local runtime_lark_mappings
                runtime_lark_mappings=$(jq '.lark_group_mappings' "$RUNTIME_FILE" 2>/dev/null)
                if [ "$runtime_lark_mappings" = "{}" ] || [ "$runtime_lark_mappings" = "null" ]; then
                    # 合并映射
                    jq --argjson mappings "$legacy_mappings" '.lark_group_mappings = $mappings' "$RUNTIME_FILE" > "$RUNTIME_FILE.tmp"
                    mv "$RUNTIME_FILE.tmp" "$RUNTIME_FILE"
                    rm -f "$LEGACY_FILE"
                    print_success "已迁移 lark_group_mapping.json 到 runtime.json"
                else
                    # runtime.json 已有映射，删除旧文件
                    rm "$LEGACY_FILE"
                    print_warning "runtime.json 已存在 lark_group_mappings，已删除旧配置文件"
                fi
            else
                # 无效 JSON，删除旧文件
                rm "$LEGACY_FILE"
                print_warning "旧配置文件格式无效，已删除"
            fi
        else
            print_warning "未安装 jq，跳过自动迁移（程序启动时会自动迁移）"
        fi
    fi
}

# 设置可执行权限
set_permissions() {
    print_header "设置执行权限"

    chmod +x remote_claude.py
    chmod +x server/server.py
    chmod +x client/client.py

    print_success "已设置执行权限"
}

# 安装快捷命令（符号链接到 bin 目录）
configure_shell() {
    print_header "安装快捷命令"

    chmod +x "$SCRIPT_DIR/bin/cla" "$SCRIPT_DIR/bin/cl" "$SCRIPT_DIR/bin/cx" "$SCRIPT_DIR/bin/cdx" "$SCRIPT_DIR/bin/remote-claude" 2>/dev/null || true

    # 优先 /usr/local/bin，权限不够则选 ~/bin 或 ~/.local/bin 中已在 PATH 里的
    BIN_DIR="/usr/local/bin"
    if ! ln -sf "$SCRIPT_DIR/bin/cla" "$BIN_DIR/cla" 2>/dev/null; then
        if [[ ":$PATH:" == *":$HOME/bin:"* ]]; then
            BIN_DIR="$HOME/bin"
        elif [[ ":$PATH:" == *":$HOME/.local/bin:"* ]]; then
            BIN_DIR="$HOME/.local/bin"
        else
            BIN_DIR="$HOME/.local/bin"
            # 自动写入 PATH 到 shell 配置文件
            export PATH="$BIN_DIR:$PATH"
            local _RC
            if [[ -n "$ZSH_VERSION" ]] || [[ "$(basename "$SHELL")" == "zsh" ]]; then
                _RC="$HOME/.zshrc"
            else
                _RC="$HOME/.bashrc"
            fi
            local _PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
            if ! grep -qF "$HOME/.local/bin" "$_RC" 2>/dev/null; then
                echo "" >> "$_RC"
                echo "# remote-claude: 快捷命令路径" >> "$_RC"
                echo "$_PATH_LINE" >> "$_RC"
                print_success "已自动将 \$HOME/.local/bin 加入 PATH（写入 $_RC）"
            fi
        fi
        mkdir -p "$BIN_DIR"
        ln -sf "$SCRIPT_DIR/bin/cla"           "$BIN_DIR/cla"          2>/dev/null || true
        ln -sf "$SCRIPT_DIR/bin/cl"            "$BIN_DIR/cl"           2>/dev/null || true
        ln -sf "$SCRIPT_DIR/bin/cx"            "$BIN_DIR/cx"           2>/dev/null || true
        ln -sf "$SCRIPT_DIR/bin/cdx"           "$BIN_DIR/cdx"          2>/dev/null || true
        ln -sf "$SCRIPT_DIR/bin/remote-claude" "$BIN_DIR/remote-claude" 2>/dev/null || true
    else
        ln -sf "$SCRIPT_DIR/bin/cl"            "$BIN_DIR/cl"           2>/dev/null || true
        ln -sf "$SCRIPT_DIR/bin/cx"            "$BIN_DIR/cx"           2>/dev/null || true
        ln -sf "$SCRIPT_DIR/bin/cdx"           "$BIN_DIR/cdx"          2>/dev/null || true
        ln -sf "$SCRIPT_DIR/bin/remote-claude" "$BIN_DIR/remote-claude" 2>/dev/null || true
    fi

    print_success "已安装 cla、cl、cx、cdx 和 remote-claude 到 $BIN_DIR"
    print_info "  cla           - 启动飞书客户端 + 以当前目录路径+时间戳为会话名启动 Claude"
    print_info "  cl            - 同 cla，但跳过权限确认"
    print_info "  cx            - 启动飞书客户端 + 以当前目录路径+时间戳为会话名启动 Codex（跳过权限）"
    print_info "  cdx           - 同 cx，但需确认权限"
    print_info "  remote-claude - Remote Claude 主命令（start/attach/list/kill/lark）"

    # 安装 shell 自动补全
    local COMPLETION_LINE="source \"$SCRIPT_DIR/scripts/completion.sh\""
    local SHELL_RC=""
    if [[ -n "$ZSH_VERSION" ]] || [[ "$(basename "$SHELL")" == "zsh" ]]; then
        SHELL_RC="$HOME/.zshrc"
    else
        SHELL_RC="$HOME/.bashrc"
    fi

    if [[ -f "$SHELL_RC" ]] && grep -qF "$SCRIPT_DIR/scripts/completion.sh" "$SHELL_RC" 2>/dev/null; then
        print_info "自动补全已配置（$SHELL_RC）"
    else
        echo "" >> "$SHELL_RC"
        echo "# remote-claude 自动补全" >> "$SHELL_RC"
        echo "$COMPLETION_LINE" >> "$SHELL_RC"
        print_success "已添加自动补全到 $SHELL_RC（重新打开终端后生效）"
    fi
}

# 重启飞书客户端
restart_lark_client() {
    print_header "重启飞书客户端"

    LARK_PID_FILE="/tmp/remote-claude/lark.pid"

    if [ ! -f "$LARK_PID_FILE" ] && ! pgrep -f "lark_client/main.py" &>/dev/null; then
        print_info "飞书客户端未运行，跳过重启"
        return
    fi

    print_info "正在重启飞书客户端..."
    cd "$SCRIPT_DIR"
    uv run python3 remote_claude.py lark restart || { WARNINGS+=("飞书客户端重启失败，请手动运行: uv run python3 remote_claude.py lark restart"); return; }
    print_success "飞书客户端已重启"
}

# 显示使用说明
show_usage() {
    print_header "安装完成！"

    cat << EOF
${YELLOW}快捷命令：${NC}

  ${GREEN}cla${NC}  - 启动飞书客户端 + 以当前目录+时间戳为会话名启动 Claude
  ${GREEN}cl${NC}   - 同 cla，但跳过权限确认
  ${GREEN}cx${NC}   - 启动飞书客户端 + 以当前目录+时间戳为会话名启动 Codex（跳过权限）
  ${GREEN}cdx${NC}  - 同 cx，但需确认权限

详细使用说明请阅读 README.md

${YELLOW}提示：${NC}请运行以下命令使 PATH 生效，或重新打开终端：
  source ~/.bash_profile

EOF
}

# 主流程
main() {
    # 解析参数
    NPM_MODE=false
    for arg in "$@"; do
        [[ "$arg" == "--npm" ]] && NPM_MODE=true
    done

    # CI 模式：跳过 tmux 版本检查（CI 环境可能没有 sudo）
    if [ -n "$CI" ]; then
        export CI_MODE=true
    fi

    echo ""
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}   Remote Claude 初始化脚本${NC}"
    echo -e "${GREEN}   双端共享 Claude CLI 工具${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""

    setup_path
    check_os
    check_uv
    check_tmux
    check_claude
    check_codex
    install_dependencies
    if ! $NPM_MODE; then
        configure_lark
    fi
    create_directories
    init_config_files
    set_permissions
    configure_shell
    restart_lark_client
    show_usage

    if [ ${#WARNINGS[@]} -gt 0 ]; then
        echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${YELLOW}⚠ 注意事项${NC}"
        echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        for w in "${WARNINGS[@]}"; do
            echo -e "${YELLOW}⚠${NC} $w"
        done
        echo ""
    fi
}

# 运行主流程
main "$@"
