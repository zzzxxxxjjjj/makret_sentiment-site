# Wind Excel 每日自动刷新与发布

这套流程每天北京时间 18:37、20:37、22:37 重试：在已登录的 Windows 用户会话中打开 Excel/Wind 插件，等待并保存工作簿，核对万得全A收盘价和换手率已到目标交易日，再生成网站数据，最后仅将指定工作簿和 JSON 上传到 GitHub `main`。Cloudflare Pages 随 GitHub 更新发布。若 Excel 或数据日期检查失败，本次不会上传旧数据。

## 运行条件

- Windows、桌面版 Excel、Wind 终端和 Excel 插件均已安装，Wind 已登录且许可证允许该机器使用。
- 执行计划任务的 Windows 用户保持登录；机器保持开机和联网。普通 GitHub 托管运行器没有本机 Wind/Excel 环境，不能代替该步骤。
- 该机器有仓库工作目录、Python/RQData 依赖及 RQData 凭据。`run_daily_update.ps1` 中的 Python 路径需按机器实际位置修改；源工作簿默认在该用户的 `OneDrive\文档\市场宽基情绪指标.xlsx`，也可设置 `BROAD_MARKET_SENTIMENT_EXCEL` 环境变量。
- 创建 GitHub fine-grained personal access token，只授权 `zzzxxxxjjjj/makret_sentiment-site`，Repository permissions 中 Contents 设为 Read and write。不要将令牌写进仓库或发到聊天里。

## 一次性配置

在将要运行计划任务的 Windows 用户下执行 `save_publish_token.ps1`，按提示输入令牌。令牌由 Windows DPAPI 加密，只有同一 Windows 用户可解密。随后执行 `install_daily_update.ps1` 安装计划任务。第一次手动运行 `run_daily_update.ps1`，检查 `daily-site-update.log`、`daily-update-status.json` 和 GitHub `main` 上的新提交；确认 Cloudflare 链接显示新的数据日期。任务失败时应查看日志，不能把“任务已触发”视作“数据已更新”。

若希望自己的电脑关机后仍刷新 Wind 数据，需将相同配置部署到持续运行的 Windows 云电脑或服务器，并确保 Wind 许可证允许在该环境中登录。当前没有这样的机器，因此计划任务只能在开机、登录的 Windows 机器上运行。RQData 云端更新继续由现有 GitHub Actions 独立运行。
