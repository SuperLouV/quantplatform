"""Chinese labels for market-facing UI payloads."""

from __future__ import annotations

from copy import deepcopy


POOL_NAME_ZH: dict[str, str] = {
    "custom_manual": "自选列表",
    "default_core": "默认列表",
    "tech_leaders": "科技龙头",
    "macro_defensive": "宏观防御",
    "nasdaq100": "纳斯达克100",
    "theme_pool": "主题池",
    "system_pool": "系统池",
    "watchlist": "观察列表",
    "tradable_universe": "可交易池",
}

SYMBOL_NAME_ZH: dict[str, str] = {
    "AAPL": "苹果",
    "MSFT": "微软",
    "NVDA": "英伟达",
    "AMZN": "亚马逊",
    "GOOGL": "谷歌",
    "GOOG": "谷歌",
    "META": "Meta",
    "TSLA": "特斯拉",
    "NFLX": "奈飞",
    "AMD": "超威半导体",
    "AVGO": "博通",
    "PLTR": "Palantir",
    "QCOM": "高通",
    "ASML": "阿斯麦",
    "ADBE": "奥多比",
    "CRM": "赛富时",
    "ORCL": "甲骨文",
    "CSCO": "思科",
    "INTC": "英特尔",
    "MU": "美光科技",
    "AMAT": "应用材料",
    "TXN": "德州仪器",
    "LRCX": "泛林集团",
    "KLAC": "科磊",
    "INTU": "Intuit",
    "ADP": "自动数据处理",
    "PYPL": "PayPal",
    "PANW": "派拓网络",
    "CRWD": "CrowdStrike",
    "SNPS": "新思科技",
    "CDNS": "铿腾电子",
    "MRVL": "迈威尔科技",
    "MSTR": "微策略",
    "COST": "好市多",
    "PEP": "百事",
    "SBUX": "星巴克",
    "BKNG": "Booking",
    "INTU": "财捷",
    "TMUS": "T-Mobile US",
    "ADI": "亚德诺半导体",
    "APP": "AppLovin",
    "ARM": "Arm",
    "QQQ": "纳指100ETF",
    "SPY": "标普500ETF",
    "TLT": "20年以上美债ETF",
    "IEF": "7-10年美债ETF",
    "SHY": "1-3年美债ETF",
    "TIP": "通胀保值债ETF",
    "GLD": "黄金ETF",
    "IAU": "黄金ETF",
    "SLV": "白银ETF",
}

SECTOR_ZH: dict[str, str] = {
    "Technology": "科技",
    "Communication Services": "通信服务",
    "Consumer Cyclical": "可选消费",
    "Consumer Defensive": "必需消费",
    "Financial Services": "金融服务",
    "Healthcare": "医疗健康",
    "Industrials": "工业",
    "Energy": "能源",
    "Basic Materials": "基础材料",
    "Utilities": "公用事业",
    "Real Estate": "房地产",
}

INDUSTRY_ZH: dict[str, str] = {
    "Consumer Electronics": "消费电子",
    "Software - Infrastructure": "基础软件",
    "Semiconductors": "半导体",
    "Internet Retail": "互联网零售",
    "Internet Content & Information": "互联网内容与信息",
    "Software - Application": "应用软件",
    "Auto Manufacturers": "汽车制造",
    "Entertainment": "娱乐流媒体",
    "Electronic Components": "电子元件",
    "Information Technology Services": "信息技术服务",
    "Capital Markets": "资本市场",
    "Gold": "黄金",
    "Silver": "白银",
    "Exchange Traded Fund": "交易所交易基金",
}

EXCHANGE_ZH: dict[str, str] = {
    "NMS": "纳斯达克",
    "NGM": "纳斯达克全球市场",
    "NCM": "纳斯达克资本市场",
    "NYQ": "纽约证券交易所",
    "PCX": "纽约证券交易所 Arca",
    "ASE": "美国证券交易所",
}


def localize_pool_name(pool_id: str, name: str | None) -> str | None:
    return POOL_NAME_ZH.get(pool_id) or name


def localize_symbol_name(symbol: str, default_name: str | None) -> str | None:
    return SYMBOL_NAME_ZH.get(symbol.upper()) or default_name


def localize_sector_name(value: str | None) -> str | None:
    if value is None:
        return None
    return SECTOR_ZH.get(value, value)


def _localize_industry_name(value: str | None) -> str | None:
    if value is None:
        return None
    return INDUSTRY_ZH.get(value, value)


def _localize_exchange_name(value: str | None) -> str | None:
    if value is None:
        return None
    return EXCHANGE_ZH.get(value, value)


def localize_snapshot_payload(payload: dict[str, object]) -> dict[str, object]:
    localized = deepcopy(payload)
    symbol = str(localized.get("symbol") or "").upper()
    company_name = localized.get("company_name")
    sector = localized.get("sector")
    industry = localized.get("industry")
    exchange = localized.get("exchange")

    localized["symbol"] = symbol
    localized["company_name_zh"] = localize_symbol_name(symbol, _as_str(company_name))
    localized["sector_zh"] = localize_sector_name(_as_str(sector))
    localized["industry_zh"] = _localize_industry_name(_as_str(industry))
    localized["exchange_zh"] = _localize_exchange_name(_as_str(exchange))
    return localized


def _as_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
