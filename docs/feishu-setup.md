# 飞书机器人配置教程

本文档只覆盖如何把 Remote Claude 接入飞书，让你可以在飞书里继续操作同一个 Claude / Codex 会话。

## 前提条件

开始前请确认：

- 已安装 Remote Claude
- 你有飞书企业自建应用的创建/发布权限
- 本机可以正常启动 `remote-claude` 或 `cla` / `cl` / `cx` / `cdx`

## 步骤一：创建飞书企业自建应用

1. 打开 [飞书开放平台](https://open.feishu.cn/)
2. 创建**企业自建应用**
3. 填写应用名称和描述，例如：
   - 应用名称：`Remote Claude`
   - 应用描述：`在飞书中共享操作 Claude Code / Codex CLI`
4. 创建完成后进入应用详情页

## 步骤二：获取 App ID 和 App Secret

在应用详情页获取：

- **App ID**
- **App Secret**

你可以用任一方式配置：

### 方式 A：首次启动时按提示填写

```bash
remote-claude lark start
```

### 方式 B：提前写入 `~/.remote-claude/.env`

```bash
FEISHU_APP_ID=your_app_id
FEISHU_APP_SECRET=your_app_secret
```

更多配置项见 [configuration.md](./configuration.md)。

## 步骤三：启用机器人能力

在飞书应用后台：

1. 进入“添加应用能力”
2. 启用**机器人**能力

## 步骤四：配置事件与回调

Remote Claude 当前使用**长连接**方式接收飞书事件与卡片回调，不需要配置公网 webhook 地址。

在飞书应用后台完成以下配置：

### 事件配置

1. 进入“事件与回调” → “事件配置”
2. 将订阅方式设置为：**使用长连接接收事件**
3. 添加事件：`接收消息 v2.0`（`im.message.receive_v1`）

### 回调配置

1. 进入“事件与回调” → “回调配置”
2. 将订阅方式设置为：**使用长连接接收回调**
3. 添加回调：`卡片回传交互`（`card.action.trigger`）

## 步骤五：配置权限

在“权限管理”中导入所需权限。

推荐直接导入项目提供的权限文件：

- [feishu-permissions.json](./feishu-permissions.json)

如果你是手动配置，请至少确保消息、卡片、用户信息等必需权限已开通。

## 步骤六：发布应用

完成上述配置后：

1. 进入“创建版本”
2. 填写版本信息
3. 发布到线上

如果没有发布，飞书里通常搜不到机器人，或机器人无法正常响应。

## 步骤七：启动并在飞书中使用

### 启动飞书客户端

```bash
remote-claude lark start
```

或直接用快捷命令启动一个会话：

```bash
cla
# 或 cl / cx / cdx
```

### 在飞书中使用机器人

1. 在飞书中搜索刚刚发布的机器人
2. 打开与机器人的会话
3. 发送 `/menu` 打开菜单
4. 根据菜单继续 attach、detach、list 或直接操作会话

## 常见问题

### 机器人搜不到或没有响应

优先检查：

- 应用是否已经发布到线上
- `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 是否正确
- 事件配置是否为**长连接接收事件**
- 回调配置是否为**长连接接收回调**
- 飞书客户端是否正在运行：

```bash
remote-claude lark status
```

### 启动飞书客户端失败

先看客户端状态与日志：

```bash
remote-claude lark status
```

客户端运维与日志排查见 [feishu-client.md](./feishu-client.md)。

### 已能收消息，但按钮点击无效

通常是“回调配置”没有正确启用长连接，或缺少 `card.action.trigger` 回调事件。

## 文档边界

- 飞书客户端启动、停止、状态、日志：见 [feishu-client.md](./feishu-client.md)
- 配置文件与环境变量：见 [configuration.md](./configuration.md)
- CLI 命令用法：见 [cli-reference.md](./cli-reference.md)
