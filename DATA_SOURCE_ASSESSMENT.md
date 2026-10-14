# 中期情绪指标免费数据源核对（2026-10-14）

当前中期分数由七项等权组成。融资活跃度、20 日融资净流入、60 日融资余额变化和 60 日市场广度由仓库内 RQData 链路更新。其余三项需要以下原始序列：万得全A PE(TTM)、万得全A股息率 TTM、10 年期国开债收益率、万得全A收盘价、万得偏债混合型基金指数（885003.WI）收盘价。

| 免费来源 | 可提供的数据 | 与现行口径的差距 |
| --- | --- | --- |
| [AKShare 债券接口](https://github.com/akfamily/akshare/blob/main/docs/data/bond/bond.md) | 中国货币网政策性金融债收益率曲线，可按期限筛选 10 年 | 有望替代债券腿，但文档写明历史窗口仅近三个月、单次不超过一个月；需先核对“国开行”曲线与现有 Wind 字段一致。 |
| [AKShare A 股接口目录](https://github.com/akfamily/akshare/blob/main/docs/tutorial.md) | 全 A 等权/中位数 PE、A 股股息率、部分指数估值 | 等权/中位数或其他全 A 统计不等于万得全A指数的 PE(TTM) 与股息率 TTM；直接替换会改变 ERP 和股债收益差。 |
| [AKShare 东方财富指数行情](https://github.com/akfamily/akshare/blob/main/docs/data/index/index.md) | 部分公开股票指数的日收盘价 | 未核实可连续取得 881001.WI 与 885003.WI 两个 Wind 指数的同口径日行情。 |
| [Wind 指数官网](https://www.windindices.com/indices/zh/AboutUs/WindIndexIntroduction) | 部分指数展示页面 | 官网列出终端、Wind API 和数据服务作为指数服务获取途径；网页可见不等于有稳定、授权的免费批量接口。 |

结论：目前未找到能够稳定、合规且保持现有七项定义不变的完整免费接口组合。因此生产网站保留 Wind/Excel 原始序列，并使用本机手动刷新后的一键发布流程；若将来接受更换指数和估值计算口径，应将其视为新指标，先并行回测和标注口径变化。
