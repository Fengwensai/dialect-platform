"""方言点文本 → 省市区 adcode 的匹配工具。

中国区划每年更新，regions 表由静态数据灌入，后续可增加高德/腾讯行政区划 API 同步。
"""
from sqlalchemy.orm import Session

from ..models.region import Region

# 区划名称后缀，匹配时剥离（长的优先）。
# 注意：不剥独立的"州"——定州/涿州/冀州/沧州 是地名的一部分，剥掉会造成误匹配。
_SUFFIXES = sorted(
    ["特别行政区", "自治州", "自治区", "自治县", "自治旗", "新区", "林区", "特区", "地区", "省", "市", "区", "县", "盟", "旗"],
    key=len,
    reverse=True,
)


def normalize(name: str | None) -> str:
    if not name:
        return ""
    s = str(name)
    for suffix in _SUFFIXES:
        s = s.replace(suffix, "")
    return s.strip()


def load_regions(db: Session) -> dict[str, Region]:
    return {r.code: r for r in db.query(Region).all()}


def find_province_by_name(regions: dict[str, Region], name: str | None) -> Region | None:
    n = normalize(name)
    if not n:
        return None
    for r in regions.values():
        if r.level == 1 and n == normalize(r.name):
            return r
    # 子串匹配，兼容 "河北" 匹配 "河北省"、"石家庄词表" 这类文件名
    for r in regions.values():
        if r.level == 1 and normalize(r.name) in n:
            return r
    return None


def province_from_filename(db: Session, filename: str | None) -> str | None:
    """从文件名提取省份，如 "河北省词表.xlsx" → '13'"""
    if not filename:
        return None
    regions = load_regions(db)
    fn = normalize(filename)
    for r in regions.values():
        if r.level == 1 and normalize(r.name) and normalize(r.name) in fn:
            return r.code
    return None


def match_region(
    db: Session,
    dialect_point: str | None,
    default_province_name: str | None = None,
) -> dict:
    """将方言点文本（如 "石家庄市-长安区"）解析为省市区 adcode。

    返回 {"province_code","city_code","district_code"}，匹配不到的部分为 None。
    """
    regions = load_regions(db)
    text = normalize(dialect_point)

    result = {"province_code": None, "city_code": None, "district_code": None}

    # 1. 省级（default_province_name 兼容 adcode 或省份名称）
    province = None
    if default_province_name:
        if default_province_name in regions and regions[default_province_name].level == 1:
            province = regions[default_province_name]
        else:
            province = find_province_by_name(regions, default_province_name)
    if province is None and text:
        for r in regions.values():
            if r.level == 1 and normalize(r.name) in text:
                province = r
                break
    if province is not None:
        result["province_code"] = province.code
        city_codes = {c.code for c in regions.values() if c.level == 2 and c.parent_code == province.code}
        city_pool = [c for c in regions.values() if c.code in city_codes]
    else:
        city_pool = [c for c in regions.values() if c.level == 2]
        city_codes = {c.code for c in city_pool}

    # 2. 区级：候选区需父级在省内；优先选"父级城市名也在文本中"的区，
    #    例如 "石家庄-桥西区" 应命中石家庄桥西区，而非张家口桥西区
    candidates = [
        r
        for r in regions.values()
        if r.level == 3 and r.parent_code in city_codes and text and normalize(r.name) in text
    ]
    district = None
    for r in candidates:
        parent = regions.get(r.parent_code)
        if parent and text and normalize(parent.name) in text:
            district = r
            break
    if district is None and candidates:
        district = candidates[0]
    if district is not None:
        result["district_code"] = district.code
        result["city_code"] = district.parent_code
        city = regions.get(district.parent_code)
        if city is not None and result["province_code"] is None:
            result["province_code"] = city.parent_code
        return result

    # 3. 市级
    for c in city_pool:
        if text and normalize(c.name) in text:
            result["city_code"] = c.code
            if result["province_code"] is None:
                result["province_code"] = c.parent_code
            break

    return result
