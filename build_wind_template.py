# -*- coding: utf-8 -*-
"""
生成 Wind Excel 桥接模板 wind_raw_template.xlsx
================================================
用途：为因子库中「不可接入 rqdata」的约 30 个外生因子提供真实数据。

关键修复（v2，解决 #VALUE!）：
  原模板把 EDB/WSD 的【日期区间】直接写进【单个单元格】
  （=EDB(B3,$B$1,$D$1,...) 会返回一个数组，单格装不下 → #VALUE!）。
  现改为 Wind 标准用法：
    - A 列放【每月最后一个交易日】（用 rqdata 预计算，保证 Wind 在该日必有值，
      消除周末/节假日缺口；rqdata 不可用时退回日历月末）；
    - 第 2 行放【Wind 代码】（可编辑、黄色高亮）；
    - 第 1 行放【数据键】（Python 映射用，勿改）；
    - 数据区每行一个日期，公式 =EDB($代码格,TEXT($A行,"yyyy-mm-dd"),"Fill=Previous")
      或 =WSD($代码格,"指标",TEXT($A行,"yyyy-mm-dd"),TEXT($A行,"yyyy-mm-dd"),"Fill=Previous")，
      即【单点取值 + 日期显式转字符串】，每格一个数，绝不会 #VALUE!。

用户步骤：
  1) 用 Wind 终端打开本文件（确保 Wind Excel 插件已加载）。
  2) 若第 2 行代码在你的账号里解析报错，改成正确的 Wind EDB 码 / 证券ID（仅改第 2 行）。
  3) 菜单【Wind】→【刷新】或按 Ctrl+Alt+F9，让公式逐行重算。
  4) 保存文件（必须保存，openpyxl 才能读到缓存值）。
  5) 运行 synthetic_factors.py，它会读取本文件并计算最终因子。
"""
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import pandas as pd

OUT = "wind_raw_template_v3.xlsx"


def _month_end_trading_dates(start="2016-01", end="2026-09"):
    """优先取每月【最后一个交易日】（保证 Wind 在该日必有值，消除周末/节假日缺口）；
    若 rqdata 不可用则退回日历月末。"""
    try:
        from retired_provider import client as rq
        rq.init()
        tds = rq.get_trading_dates(f"{start}-01", f"{end}-30")
        ts = pd.to_datetime(list(tds))
        me = ts.groupby(ts.to_period("M")).max()
        return [d.date() for d in me]
    except Exception as e:
        print("[WARN] rqdata 取交易日失败，退回日历月末:", e)
        return list(pd.period_range(start, end, freq="M").to_timestamp(how="end").date)


# 月频日期：每月最后一个交易日（2016-01 ~ 2026-09），与因子面板对齐
DATES = _month_end_trading_dates()

# 每个数据键定义：(数据键, Wind代码占位, 类型EDB/WSD, WSD指标, 频率M/D, 说明)
# 类型 EDB：宏观/日频指标（代码即指标码）
# 类型 WSD：证券类（代码=证券ID，指标=字段）
SHEETS = {
    "宏观政策": [
        ("M1_YOY",        "M0001383", "EDB", "", "M", "M1 同比（货币增速）"),
        ("M2_YOY",        "M0001384", "EDB", "", "M", "M2 同比（货币增速）"),
        ("SF_STOCK_YOY",  "M0001872", "EDB", "", "M", "社融存量同比（信用方向/信贷脉冲基础）"),
        ("LOAN_MLT_YOY",  "M0017118", "EDB", "", "M", "金融机构中长期贷款同比（中长期信贷脉冲基础）"),
        ("CPI_YOY",       "M0000615", "EDB", "", "M", "CPI 同比（通胀剪刀差）"),
        ("PPI_YOY",       "M0000745", "EDB", "", "M", "PPI 同比（通胀剪刀差/通胀方向）"),
        ("RETAIL_YOY",    "M0000747", "EDB", "", "M", "社会消费品零售总额同比"),
        ("EXPORT_YOY",    "M0000808", "EDB", "", "M", "出口金额同比"),
        ("IND_PROFIT_YOY","M0002123", "EDB", "", "M", "规上工业企业利润同比"),
        ("OMO_NET",       "M0041095", "EDB", "", "D", "公开市场操作(OMO)净投放（日，月频取月末）"),
        ("SLF_BAL",       "M0035001", "EDB", "", "M", "常备借贷便利(SLF)余额"),
        ("MLF_BAL",       "M0035002", "EDB", "", "M", "中期借贷便利(MLF)余额"),
        ("PSL_BAL",       "M0035003", "EDB", "", "M", "抵押补充贷款(PSL)余额"),
        ("RMB_FX",        "M0000180", "EDB", "", "D", "USD/CNY 人民币中间价（升值=下行=看多，取负向）"),
    ],
    "海外": [
        ("US10Y",     "US10Y", "WSD", "yield", "D", "美国10年期国债收益率"),
        ("US01Y",     "US01Y", "WSD", "yield", "D", "美国1年期国债收益率（人民币风险溢价基础）"),
        ("DXY",       "DXY",   "WSD", "close", "D", "美元指数"),
        ("FED_BS",    "M0038001", "EDB", "", "M", "美联储资产负债表规模（海外流动性基础）"),
        ("VIX",       "VIX",   "WSD", "close", "D", "标普500波动率指数（海外风险厌恶基础）"),
        ("CN_CDS5Y",  "CDS0001", "WSD", "close", "D", "中国5年主权CDS利差（bps）"),
    ],
    "资金流": [
        ("NORTHBOUND_CUM",   "880008",  "WSD", "amount", "D", "北向资金(沪深港通)累计净流入（近60日口径由Python算）"),
        ("EQUITY_FUND_ISSUE","M0029001","EDB", "", "M", "股票型/混合型基金发行份额"),
        ("IPO_PROCEEDS",     "M0029002","EDB", "", "M", "IPO 筹资额（净募资）"),
        ("NEW_ACCOUNTS",     "M0029003","EDB", "", "M", "中登新增投资者（A股新增开户）数量"),
    ],
}

thin = Side(style="thin", color="BFBFBF")
border = Border(left=thin, right=thin, top=thin, bottom=thin)
hdr_fill = PatternFill("solid", fgColor="1F4E78")
hdr_font = Font(color="FFFFFF", bold=True)
code_fill = PatternFill("solid", fgColor="FFF2CC")
date_fill = PatternFill("solid", fgColor="DDEBF7")
note_fill = PatternFill("solid", fgColor="FCE4D6")

wb = openpyxl.Workbook()
wb.remove(wb.active)

# 说明 sheet
ws0 = wb.create_sheet("使用说明")
ws0["A1"] = "Wind Excel 桥接模板 · 使用说明（v2：逐行单点取值，修复 #VALUE!）"
ws0["A1"].font = Font(bold=True, size=14)
guide = [
    "",
    "本模板为因子库中「不可接入 rqdata」的约 30 个外生因子提供真实数据。",
    "",
    "【重要】v2 已修复 #VALUE!：Wind 的区间取数必须逐行单点取，不能把一个"
    "时间序列塞进单个单元格。本模板 A 列为真实日期，第 2 行为 Wind 代码，",
    "第 3 行起每行一个日期、对应一个数值。",
    "",
    "步骤：",
    "  1) 用 Wind 终端打开本文件（确保 Wind Excel 插件已加载）。",
    "  2) 若第 2 行某代码在你的账号里解析报错，改成正确的 Wind EDB 码 / 证券ID（仅改第 2 行）。",
    "  3) 菜单【Wind】→【刷新】或按 Ctrl+Alt+F9，让公式逐行重算（首次可能较慢）。",
    "  4) 保存文件（必须保存，openpyxl 才能读到缓存值）。",
    "  5) 运行 synthetic_factors.py，它会读取本文件并计算最终因子。",
    "",
    "每个数据 sheet 的约定：",
    "  第1行 = 数据键（Python 映射用，勿改）",
    "  第2行 = Wind代码（可编辑，黄色高亮，只改这一行）",
    "  第3行起 = A列日期 + 各指标逐行数值（公式自动，勿手填）",
    "",
    "若某行仍出现 #VALUE!：说明该日期该指标无值（Wind 返回空），",
    "属正常缺口；Python 端会 dropna 处理。若整列全为 #VALUE!，",
    "则代码可能仍需核对（但你说代码已正确，通常为个别日期缺口）。",
]
for i, line in enumerate(guide, start=2):
    ws0.cell(i, 1, line)

# 字段说明 sheet（纯文档，便于核对每个键含义）
wsd_sheet = wb.create_sheet("字段说明")
fhead = ["数据键", "Wind代码", "类型", "WSD指标", "频率", "所属sheet", "说明"]
for j, h in enumerate(fhead, 1):
    c = wsd_sheet.cell(1, j, h); c.fill = hdr_fill; c.font = hdr_font; c.border = border
fr = 2
for sheet, rows in SHEETS.items():
    for key, code, typ, ind, freq, desc in rows:
        vals = [key, code, typ, ind, freq, sheet, desc]
        for j, v in enumerate(vals, 1):
            wsd_sheet.cell(fr, j, v).border = border
        fr += 1
for j, w in enumerate([18, 14, 8, 10, 7, 10, 46], 1):
    wsd_sheet.column_dimensions[get_column_letter(j)].width = w

# 数据 sheets
for sheet, rows in SHEETS.items():
    ws = wb.create_sheet(sheet)
    ncol = len(rows)
    # 第1行：表头（数据键）
    ws.cell(1, 1, "日期").fill = hdr_fill
    ws.cell(1, 1).font = hdr_font
    ws.cell(1, 1).border = border
    for j, (key, code, typ, ind, freq, desc) in enumerate(rows, start=2):
        c = ws.cell(1, j, key); c.fill = hdr_fill; c.font = hdr_font; c.border = border
        c.alignment = Alignment(horizontal="center", wrap_text=True)
    # 第2行：Wind 代码（可编辑）
    ws.cell(2, 1, "←Wind代码(可编辑)").fill = code_fill
    ws.cell(2, 1).font = Font(bold=True, italic=True)
    ws.cell(2, 1).border = border
    for j, (key, code, typ, ind, freq, desc) in enumerate(rows, start=2):
        cc = ws.cell(2, j, code); cc.fill = code_fill; cc.border = border
        cc.font = Font(bold=True)
    # 第3行起：日期 + 公式
    for i, dt in enumerate(DATES, start=3):
        dr = ws.cell(i, 1, dt); dr.fill = date_fill; dr.border = border
        dr.number_format = "yyyy-mm-dd"
        for j, (key, code, typ, ind, freq, desc) in enumerate(rows, start=2):
            col = get_column_letter(j)
            code_ref = f"${col}$2"
            date_ref = f"$A{i}"
            if typ == "EDB":
                formula = f'=EDB({code_ref},TEXT({date_ref},"yyyy-mm-dd"),"Fill=Previous")'
            else:
                formula = f'=WSD({code_ref},"{ind}",TEXT({date_ref},"yyyy-mm-dd"),TEXT({date_ref},"yyyy-mm-dd"),"Fill=Previous")'
            fc = ws.cell(i, j, formula); fc.border = border
    # 列宽
    ws.column_dimensions["A"].width = 14
    for j in range(2, ncol + 2):
        ws.column_dimensions[get_column_letter(j)].width = 16
    # 冻结前两行与日期列
    ws.freeze_panes = "B3"

wb.save(OUT)
print("已生成", OUT, "sheets:", wb.sheetnames, "日期行数:", len(DATES))
