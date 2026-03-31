# 飞书机器人配置教程

本教程介绍如何配置飞书企业自建应用，实现 Remote Claude 的飞书端操作功能。

## 前提条件

- 飞书企业管理员权限
- 已安装并配置好 Remote Claude

## 步骤一：创建飞书应用

1. 登录 [飞书开放平台](https://open.feishu.cn/)
2. 点击「创建企业自建应用」
3. 填写应用名称和描述，例如：
   - 应用名称：`Remote Claude`
   - 应用描述：`远程操作 Claude Code 的飞书机器人`
4. 选择应用图标，点击「创建」

## 步骤二：获取应用凭证

创建完成后，在应用详情页可以看到：

- **App ID**：应用的唯一标识
- **App Secret**：应用的密钥

将这两个值配置到 Remote Claude：

```bash
# 创建配置文件
mkdir -p ~/.remote-claude
cat > ~/.remote-claude/.env << 'EOF'
FEISHU_APP_ID=your_app_id
FEISHU_APP_SECRET=your_app_secret
EOF

# 设置文件权限
chmod 600 ~/.remote-claude/.env
```

或者在首次启动时按提示输入：

```bash
remote-claude lark start
# 系统会提示输入 App ID 和 App Secret
```

## 步骤三：配置应用能力

### 添加机器人能力

1. 在应用管理页面，点击「应用能力」
2. 点击「添加应用能力」
3. 选择「机器人」，启用机器人功能

### 配置事件订阅

1. 点击「事件订阅」
2. 配置请求网址（需要公网可访问的地址）：
   ```
   https://your-server.com/webhook
   ```
3. 添加以下事件：
   - `接收消息 v2.0`（im.message.receive_v1）
   - `卡片回传交互`（card.action.trigger）

### 配置权限

在「权限管理」页面，添加以下权限：

**消息权限：**
- `im:message` - 获取与发送单聊、群组消息
- `im:message:send_as_bot` - 以应用身份发消息
- `im:message.p2p_msg` - 获取用户发给机器人的单聊消息
- `im:message.p2p_msg:readonly` - 读取用户发给机器人的单聊消息

**卡片权限：**
- `card:card` - 使用卡片能力
- `card:card:readonly` - 获取卡片信息

**用户权限：**
- `contact:user.base:readonly` - 获取用户基本信息

完整权限列表参见 [feishu-permissions.json](./feishu-permissions.json)。

## 步骤四：发布应用

1. 在应用管理页面，点击「版本管理与发布」
2. 点击「创建版本」
3. 填写版本号和更新说明
4. 点击「保存并发布」
5. 等待审核通过（企业管理员审批）

## 步骤五：使用机器人

### 启动飞书客户端

```bash
# 启动
remote-claude lark start

# 查看状态
remote-claude lark status
```

### 在飞书中使用

1. 在飞书搜索框中搜索你的机器人名称
2. 发送 `/menu` 打开功能菜单
3. 可用命令：
   - `/menu` - 显示功能菜单
   - `/attach <会话名>` - 连接到会话
   - `/detach` - 断开会话连接
   - `/list` - 列出所有会话
   - `/help` - 显示帮助信息

## 事件回调配置详解

### 本地开发环境

如果需要在本地开发测试，可以使用内网穿透工具：

**使用 ngrok：**

```bash
# 安装 ngrok
brew install ngrok

# 启动内网穿透
ngrok http 8080

# 将生成的 URL 配置到飞书事件订阅
# 例如：https://xxx.ngrok.io/webhook
```

**使用 frp：**

```bash
# frp 客户端配置
[web]
type = http
local_port = 8080
custom_domains = your-domain.com
```

### 生产环境

生产环境建议配置：

1. **HTTPS**：必须使用 HTTPS 协议
2. **域名**：使用稳定的域名
3. **负载均衡**：多实例部署时配置负载均衡

## 常见问题

### 机器人无响应

**检查清单：**

1. 飞书客户端是否正常运行
   ```bash
   remote-claude lark status
   ```

2. 应用凭证是否正确
   ```bash
   cat ~/.remote-claude/.env
   ```

3. 事件订阅是否配置正确
   - 检查请求网址是否可访问
   - 检查是否添加了必要的事件

4. 权限是否完整
   - 对照权限列表检查是否遗漏

### 消息发送失败

**可能原因：**

1. 应用未发布或未启用
2. 用户未与机器人建立单聊会话
3. 权限不足

**解决方案：**

```bash
# 查看日志
tail -f ~/.remote-claude/logs/lark_client.log

# 重启客户端
remote-claude lark restart
```

### 卡片更新失败

**可能原因：**

1. 卡片 token 过期
2. 卡片内容过长

**解决方案：**

在配置中启用卡片过期功能：

```json
{
  "card": {
    "expiry": {
      "enabled": true,
      "expiry_seconds": 3600
    }
  }
}
```

## 安全建议

1. **保护凭证**：
   - 不要将 App Secret 提交到代码仓库
   - 定期轮换 App Secret

2. **限制权限**：
   - 只申请必要的权限
   - 遵循最小权限原则

3. **监控日志**：
   - 定期检查异常访问
   - 设置告警机制

## 相关文档

- [飞书开放平台文档](https://open.feishu.cn/document/)
- [飞书卡片开发指南](https://open.larkoffice.com/document/feishu-cards/card-json-v2-structure)
- [配置说明](./configuration.md)
- [飞书客户端管理](./feishu-client.md)
