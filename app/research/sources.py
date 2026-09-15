"""权威公开源注册表:用于对搜索结果排序,优先抓取官方/权威站点。"""
from urllib.parse import urlparse

# 按可信度分级的公开站点后缀(0 = 最权威)
_AUTHORITY_TIERS: dict[int, tuple[str, ...]] = {
    0: (".gov.cn", "stats.gov.cn", "miit.gov.cn", "ndrc.gov.cn", "mofcom.gov.cn"),
    1: ("people.com.cn", "xinhuanet.com", "news.cn", "ce.cn", "cnr.cn"),
    2: ("iresearch.cn", "analysys.cn", "199it.com", "eastmoney.com", "sina.com.cn", "163.com"),
    3: ("baike.baidu.com", "zhihu.com", "sohu.com", "163.com"),
}


def authority_rank(url: str) -> int:
    """返回来源可信度等级,数字越小越权威;未知站点为 4。"""
    host = (urlparse(url).netloc or "").lower()
    if not host:
        return 4
    for tier, suffixes in sorted(_AUTHORITY_TIERS.items()):
        for suffix in suffixes:
            if host == suffix.lstrip(".") or host.endswith(suffix):
                return tier
    return 4


def source_name_for(url: str) -> str:
    """从 URL 提取来源机构名(注册表已知站点优先)。"""
    host = (urlparse(url).netloc or "").lower()
    known = {
        "stats.gov.cn": "国家统计局",
        "gov.cn": "中国政府网",
        "miit.gov.cn": "工业和信息化部",
        "ndrc.gov.cn": "国家发展改革委",
        "mofcom.gov.cn": "商务部",
        "people.com.cn": "人民网",
        "xinhuanet.com": "新华网",
        "news.cn": "新华网",
        "ce.cn": "中国经济网",
        "iresearch.cn": "艾瑞咨询",
        "analysys.cn": "易观分析",
        "199it.com": "199IT互联网数据中心",
        "baike.baidu.com": "百度百科",
    }
    for suffix, name in known.items():
        if host == suffix or host.endswith(suffix):
            return name
    return host
