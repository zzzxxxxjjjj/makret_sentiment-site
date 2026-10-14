# Wind Excel 每日自动刷新与发布

手动在 Excel 中刷新并保存 `市场宽基情绪指标.xlsx` 后，双击 `publish_saved_excel.cmd` 即可重新生成网站数据并上传到 GitHub `main`。备用计划任务在工作日北京时间 10:45 和 11:45 运行，读取已保存的表格，不会再次启动 Excel。流程会核对万得全A收盘价、换手率和中期情绪均已到最近完成交易日；校验失败时不会上传旧数据。Cloudflare Pages 随 GitHub 更新发布。

## 运行条件

- Windows、桌面版 Excel、Wind 终端和 Excel 插件均已安装，Wind 已登录且许可证允许该机器使用。
- 执行计划任务的 Windows 用户保持登录；机器保持开机和联网。普通 GitHub 托管运行器没有本机 Wind/Excel 环境，不能代替该步骤。
- 该机器有仓库工作目录、Python/RQData 依赖及 RQData 凭据。`run_daily_update.ps1` 中的 Python 路径需按机器实际位置修改；源工作簿默认在该用户的 `OneDrive\文档\市场宽基情绪指标.xlsx`，也可设置 `BROAD_MARKET_SENTIMENT_EXCEL` 环境变量。
- 按 [GitHub 官方说明](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)创建 fine-grained personal access token，只授权 `zzzxxxxjjjj/makret_sentiment-site`，Repository permissions 中 Contents 设为 Read and write。不要将令牌写进仓库或发到聊天里。

## 一次性配置

备用计划任务已安装；在凭据配置前保持禁用。在当前 Windows 用户下双击 `configure_publish.cmd`，按提示输入令牌。令牌由 Windows DPAPI 加密，只有同一 Windows 用户可解密；配置成功后脚本会启用备用任务。以后在 Excel 完成刷新并保存后，双击 `publish_saved_excel.cmd`；它会读取已保存的表格，不需要再次打开 Excel。检查 `daily-site-update.log`、`daily-update-status.json` 和 GitHub `main` 上的新提交，并确认 Cloudflare 链接显示新的数据日期。任务失败时应查看日志，不能把“任务已触发”视作“数据已更新”。

上午执行时，网站数据目标为上一个已完成交易日；当天的 RQData 日线要等当晚云端更新。你的电脑必须在手动发布或备用任务运行期间保持开机、联网和 Windows 用户已登录。RQData 云端更新继续由现有 GitHub Actions 独立运行。

手动发布只上传已刷新工作簿、Wind 提取数据和重新生成的网站页面缓存；RQData 原始数据仍由 GitHub Actions 管理，避免本机副本覆盖云端更新。
