# 体育热榜 24 小时监控

监控 [今日热榜](https://tophub.today/) 体育板块下 4 个榜单，每 5 分钟采集一次 Top10，按出现次数生成日报。

## 监控榜单

| 平台 | 榜单 |
|------|------|
| 新浪体育新闻 | 点击量排行 |
| 抖音 | 体育榜 |
| 虎扑社区 | NBA论坛热帖 |
| 懂球帝 | 今日头条 |

## 报告时间

- **18:30**：统计过去 10 小时（08:30 ~ 18:30），输出各平台 Top5 + 全站 Top5
- **08:30**：统计过去 14 小时（昨日 18:30 ~ 08:30），输出各平台 Top5 + 全站 Top5

报告追加写入 `data/hotlist_report.txt`。若已配置 PushPlus，同一时间会将**本次刚生成的报告**推送到微信。

## 手机推送（微信 ClawBot）

通过 [PushPlus](https://www.pushplus.plus) 的 **微信 ClawBot** 渠道，将报告推送到微信。

1. 在 [pushplus.plus](https://www.pushplus.plus) 注册并完成**实名认证**（未实名时接口返回 905，无法发送）。
2. **个人中心 → 渠道配置 → 微信 ClawBot → 立即绑定**（扫码绑定）。
3. 绑定后向 ClawBot **主动发一条消息**，点击「我已发送」，监听状态变为「已激活」。
4. 复制用户 Token，设置环境变量（参考 [`.env.example`](.env.example)）：

```powershell
$env:PUSHPLUS_TOKEN="你的Token"
$env:PUSHPLUS_CHANNEL="clawbot"
```

5. 保持 `python main.py` 常驻（或配置 Windows 任务计划程序开机启动）。
6. 每天 **08:30**、**18:30** 自动生成报告并推送当次报告正文到微信。

**ClawBot 使用限制**（[官方说明](https://pushplus.plus/doc/channel/clawbot.html)）：

- 每推送 **10 条**后，需再主动发一条消息给 ClawBot
- 每 **24 小时**内需至少主动对话一次，否则后续推送可能失败

建议每天固定时间给 ClawBot 发一条消息保持激活。本项目每天 2 次推送，24 小时限制是主要注意点。

未设置 `PUSHPLUS_TOKEN` 时仅写入 `data/hotlist_report.txt`，不影响采集与报告生成。

### 推送联调

生成测试报告后，用晚间报告内容试发一条推送：

```bash
python verify.py --push
```

需已设置 `PUSHPLUS_TOKEN`。

## 安装与运行

需要 Python 3.10 或更高版本。

```bash
pip install -r requirements.txt
python main.py
```

启动后会打开**桌面监控窗口**，立即采集一次并在窗口中展示 4 个平台的 Top10 热榜，之后每 5 分钟自动刷新。

### 窗口操作

- **实时展示**：4 个平台热榜以 2×2 网格排列，显示排名与标题
- **双击条目**：在浏览器中打开对应链接
- **立即刷新**：点击右上角按钮手动触发一次抓取
- **选中条目**：底部状态栏显示完整标题
- **关闭窗口**：停止后台调度并退出程序

## Windows 开机自启

1. 打开「任务计划程序」
2. 创建基本任务 → 触发器选「计算机启动时」或「登录时」
3. 操作选「启动程序」：`python.exe`，参数填 `main.py` 完整路径，起始于项目目录

也可使用 [NSSM](https://nssm.cc/) 将程序注册为 Windows 服务。

## 数据文件

- `data/records.db`：SQLite 采集记录
- `data/hotlist_report.txt`：汇总报告
