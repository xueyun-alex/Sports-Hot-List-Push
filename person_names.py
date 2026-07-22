import logging
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Set, Tuple

import jieba
import jieba.posseg as pseg

from storage import TitleCountRecord


jieba.setLogLevel(logging.WARNING)

_CJK = r"\u3400-\u9fff"
_NAME_FLAGS = {"nr", "nrt", "nrfg"}
_CONNECTORS = {"-", "·", "•", "・"}
_BLOCKING_FLAGS = {"c", "m", "p", "u", "v", "x"}

# Explicit aliases improve common sports/AI names that tokenizers frequently split.
_ALIASES: Dict[str, str] = {
    "勒布朗-詹姆斯": "詹姆斯",
    "勒布朗·詹姆斯": "詹姆斯",
    "勒布朗詹姆斯": "詹姆斯",
    "勒布朗": "詹姆斯",
    "期韩佳琪": "韩佳琪",
    "若昂-马里奥": "若昂-马里奥",
    "秀托马斯": "托马斯",
    "LeBron James": "詹姆斯",
    "保罗乔治": "保罗-乔治",
    "保罗·乔治": "保罗-乔治",
    "Paul George": "保罗-乔治",
    "山姆·奥特曼": "萨姆·奥特曼",
    "山姆奥特曼": "萨姆·奥特曼",
    "Sam Altman": "萨姆·奥特曼",
    "Elon Musk": "马斯克",
    "埃隆·马斯克": "马斯克",
    "Jensen Huang": "黄仁勋",
}

_KNOWN_NAMES = {
    "C罗",
    "字母哥",
    "詹姆斯",
    "梅西",
    "内马尔",
    "库里",
    "杜兰特",
    "哈登",
    "科比",
    "乔丹",
    "恩比德",
    "欧文",
    "库明加",
    "爱德华兹",
    "阿德巴约",
    "杨瀚森",
    "姚明",
    "武磊",
    "孙兴慜",
    "亚马尔",
    "莫德里奇",
    "黄仁勋",
    "马斯克",
    "李飞飞",
    "吴恩达",
    "杨立昆",
    "扎克伯格",
    "比尔·盖茨",
}

_STOPWORDS = {
    "马刺",
    "尤文",
    "罗马",
    "法国",
    "西班牙",
    "英格兰",
    "阿根廷",
    "葡萄牙",
    "中国",
    "美国",
    "欧洲",
    "亚洲",
    "浙江",
    "山东",
    "广东",
    "南京",
    "宁波",
    "梅州",
    "大连",
    "懂球帝",
    "新浪彩票",
    "流言板",
    "世界杯",
    "欧洲杯",
    "奥运会",
    "全明星",
    "半场",
    "战报",
    "英超",
    "凯尔特人",
    "森林狼",
    "天狼星",
    "奥卢",
    "桑德菲杰",
    "桑托斯",
    "维拉",
    "小狗",
    "老虎",
    "乌龙",
    "文明",
    "明智",
    "封盖",
    "全大胜",
    "国青男",
    "曾飞",
    "莱斯特",
    "奥胡斯",
    "沙佩科",
    "阿森纳",
    "本赛季",
    "足彩彩果",
    "The Download",
    "White House",
    "阿里",
    "华为",
    "谷歌",
    "哈佛",
    "富士康",
    "支付宝",
    "英飞凌",
    "金山",
    "宇树",
    "普渡",
    "后摩",
    "灵波",
    "元宝",
    "官宣",
    "推理",
    "塞进",
    "海亮",
    "滴滴在WAIC",
    "连卫星",
    "的高德",
    "解密",
    "夏联",
    "中超",
    "国青",
    "男篮",
    "女足",
    "球队",
    "球员",
    "主教练",
    "官方",
    "记者",
    "媒体",
    "跟队",
    "美记",
    "队记",
    "意媒",
    "每体",
    "湖媒",
    "巴媒",
    "曼晚",
    "阿斯",
    "韩媒",
    "Goal",
    "RMC",
    "talkSPORT",
    "竞彩大势",
    "竞彩欧亚对照",
    "懂球帝海报君",
    "NBA夏联一阵",
    "NBA夏联二阵",
}

_SOURCE_SUFFIXES = (
    "官方",
    "记者",
    "媒体",
    "日报",
    "周报",
    "晚报",
    "时报",
    "新闻网",
    "俱乐部",
    "球队",
    "公司",
    "研究院",
)
_NON_PERSON_SUFFIXES = (
    "队",
    "国",
    "省",
    "市",
    "城",
    "杯",
    "赛",
    "榜",
    "奖",
    "组",
    "网",
    "媒",
    "报",
    "体育",
    "足球",
    "篮球",
)
_ROLE_PREFIXES = (
    "前主帅",
    "主帅",
    "球员",
    "状元",
    "榜眼",
    "名记",
    "美记",
    "队记",
    "记者",
    "丈夫",
    "妻子",
    "男友",
    "女友",
    "双MVP",
    "MVP",
    "次轮秀",
    "秀",
)

_PARTICLE_SUFFIXES = (
    "可能的",
    "可能",
    "倾向",
    "已经",
    "正在",
    "将会",
    "将",
    "也",
    "若",
    "的",
    "在",
    "都没",
    "都",
    "今夏",
    "头球",
)
_FORBIDDEN_FRAGMENTS = {
    "他最",
    "她最",
    "不可能",
    "只是为",
    "那是",
    "年底",
    "交易",
    "发布会",
    "专项队员",
    "模拟",
    "回复",
    "预测",
    "等三人",
    "理由",
    "一文",
    "自己",
    "推广",
    "感悟",
    "揭秘",
    "流程",
    "同时",
    "有人",
    "终于",
    "不对称",
    "太猛",
    "分享",
    "专业操作",
    "闭环",
    "日报",
}

_ENGLISH_FULL_NAME_RE = re.compile(
    r"(?<![A-Za-z])"
    r"[A-Z][a-z]{1,24}(?:[-'’][A-Z][a-z]{1,24})?"
    r"(?:\s+[A-Z][a-z]{1,24}(?:[-'’][A-Z][a-z]{1,24})?){1,3}"
    r"(?![A-Za-z])"
)
_SPEAKER_RE = re.compile(
    rf"(?:^|[\s，,。；;、\]\[【】])"
    rf"(?P<name>[{_CJK}A-Za-z][{_CJK}A-Za-z·•・\-']{{1,23}})"
    r"[：:]"
)
_ACTION_RE = re.compile(
    rf"(?:^|[\s，,。；;：:、\]\[【】])"
    rf"(?P<name>[{_CJK}A-Za-z][{_CJK}A-Za-z·•・\-']{{1,15}}?)"
    r"(?=(?:破门|建功|传射|染红|当选|加盟|回归|复出|退役|转会|留队|"
    r"确认|表示|透露|回应|认为|强调|建议|坦言|谈到|谈及|晒出|分享|"
    r"倾向|希望|执教|被征召|领衔|宣布|告别|签约|入选|告知|回复|"
    r"转述|准备|入镜|热恋|获奖|夺冠|进球|助攻|砍下|得到|贡献|缺席|出战))"
)
_ROLE_NAME_RE = re.compile(
    rf"(?:前主帅|主帅|球员|状元|榜眼|丈夫|妻子|男友|女友)"
    rf"(?P<name>[{_CJK}][{_CJK}·•・\-]{{1,9}}?)"
    r"(?=(?:执教|加盟|回归|复出|退役|转会|留队|被征召|入选|入镜|热恋))"
)
_RELATION_RE = re.compile(
    rf"(?:^|[\s，,。；;：:、\]\[【】])"
    rf"(?P<left>[{_CJK}]{{2,6}})[与和](?P<right>[{_CJK}]{{2,6}})"
    r"(?=(?:热恋|同框|订婚|结婚|离婚|交往))"
)


@dataclass(frozen=True)
class PersonCountResult:
    name: str
    count: int
    headline_count: int
    platform_keys: Tuple[str, ...]
    latest_title: str
    latest_url: Optional[str]
    last_seen: str


@dataclass
class _Token:
    word: str
    flag: str


@dataclass
class _PersonAccumulator:
    count: int = 0
    headline_count: int = 0
    platform_counts: Dict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    latest_title: str = ""
    latest_url: Optional[str] = None
    last_seen: str = ""


def _normalize_text(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "").strip()


def canonicalize_person_name(name: str) -> str:
    normalized = _normalize_text(name)
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = normalized.strip(" \t\r\n#@，,。；;：:、!！?？()（）[]【】<>《》\"“”")
    for prefix in _ROLE_PREFIXES:
        if normalized.startswith(prefix) and len(normalized) > len(prefix) + 1:
            normalized = normalized[len(prefix) :]
            break
    changed = True
    while changed:
        changed = False
        for suffix in _PARTICLE_SUFFIXES:
            if normalized.endswith(suffix) and len(normalized) > len(suffix) + 1:
                normalized = normalized[: -len(suffix)]
                changed = True
                break
    return _ALIASES.get(normalized, normalized)


def _is_valid_candidate(name: str) -> bool:
    if not name or name in _STOPWORDS:
        return False
    if any(char.isdigit() for char in name):
        return False
    if any(fragment in name for fragment in _FORBIDDEN_FRAGMENTS):
        return False
    if "与" in name or "和" in name:
        return False
    if any(name.endswith(suffix) for suffix in _SOURCE_SUFFIXES):
        return False

    has_cjk = bool(re.search(rf"[{_CJK}]", name))
    if has_cjk:
        compact = re.sub(r"[·•・\-]", "", name)
        if not 2 <= len(compact) <= 10:
            return False
        if name not in _KNOWN_NAMES and any(
            compact.endswith(suffix) for suffix in _NON_PERSON_SUFFIXES
        ):
            return False
        return True

    if name in _STOPWORDS or name.isupper():
        return False
    return bool(_ENGLISH_FULL_NAME_RE.fullmatch(name))


def _add_candidate(candidates: Set[str], raw_name: str) -> None:
    name = canonicalize_person_name(raw_name)
    if _is_valid_candidate(name):
        candidates.add(name)


def _extract_pos_names(title: str) -> Iterable[str]:
    tokens = [_Token(pair.word, pair.flag) for pair in pseg.cut(title)]
    for index, token in enumerate(tokens):
        if token.flag not in _NAME_FLAGS:
            continue

        start = index
        end = index + 1

        while end < len(tokens) and tokens[end].flag in _NAME_FLAGS:
            end += 1

        if start > 0:
            previous = tokens[start - 1]
            if (
                len(previous.word) == 1
                and re.fullmatch(rf"[{_CJK}]", previous.word)
                and previous.flag not in _BLOCKING_FLAGS
                and len(token.word) >= 2
            ):
                start -= 1

        if end < len(tokens):
            following = tokens[end]
            if (
                len(following.word) == 1
                and re.fullmatch(rf"[{_CJK}]", following.word)
                and following.flag not in _BLOCKING_FLAGS
                and token.flag == "nrt"
            ):
                end += 1

        if start >= 2 and tokens[start - 1].word in _CONNECTORS:
            left = tokens[start - 2]
            if (
                left.flag in _NAME_FLAGS or left.flag in {"n", "ns", "eng"}
            ) and 1 <= len(left.word) <= 12:
                start -= 2

        if end + 1 < len(tokens) and tokens[end].word in _CONNECTORS:
            right = tokens[end + 1]
            if (
                right.flag in _NAME_FLAGS or right.flag in {"n", "ns", "eng"}
            ) and 1 <= len(right.word) <= 12:
                end += 2

        yield "".join(part.word for part in tokens[start:end])


def extract_person_names(title: str) -> Set[str]:
    """Extract unique person names mentioned in one hot-list headline."""
    normalized = _normalize_text(title)
    if not normalized:
        return set()

    candidates: Set[str] = set()

    for alias, canonical in sorted(
        _ALIASES.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if alias.casefold() in normalized.casefold():
            _add_candidate(candidates, canonical)
    for known_name in _KNOWN_NAMES:
        if known_name.casefold() in normalized.casefold():
            _add_candidate(candidates, known_name)

    for match in _SPEAKER_RE.finditer(normalized):
        _add_candidate(candidates, match.group("name"))
    for match in _ACTION_RE.finditer(normalized):
        _add_candidate(candidates, match.group("name"))
    for match in _ROLE_NAME_RE.finditer(normalized):
        _add_candidate(candidates, match.group("name"))
    for match in _RELATION_RE.finditer(normalized):
        _add_candidate(candidates, match.group("left"))
        _add_candidate(candidates, match.group("right"))
    for raw_name in _extract_pos_names(normalized):
        _add_candidate(candidates, raw_name)

    protected = {
        canonicalize_person_name(name)
        for name in _KNOWN_NAMES.union(_ALIASES.values())
        if canonicalize_person_name(name) in candidates
    }
    candidates = {
        candidate
        for candidate in candidates
        if candidate in protected
        or not any(
            known in candidate and known != candidate for known in protected
        )
    }
    candidates = {
        candidate
        for candidate in candidates
        if candidate in protected
        or not any(
            candidate != other and candidate in other for other in candidates
        )
    }
    return candidates


def _seen_timestamp(value: str) -> float:
    try:
        return datetime.fromisoformat(value).timestamp()
    except (TypeError, ValueError):
        return 0.0


def rank_person_mentions(
    records: Iterable[TitleCountRecord],
    query: str = "",
    limit: int = 100,
) -> Tuple[List[PersonCountResult], int]:
    """Rank people by the number of captured hot-list appearances."""
    accumulators: Dict[str, _PersonAccumulator] = {}

    for record in records:
        for name in extract_person_names(record.title):
            item = accumulators.setdefault(name, _PersonAccumulator())
            item.count += int(record.count)
            item.headline_count += 1
            item.platform_counts[record.platform] += int(record.count)
            if not item.last_seen or record.last_seen > item.last_seen:
                item.latest_title = record.title
                item.latest_url = record.url
                item.last_seen = record.last_seen

    query_text = canonicalize_person_name(query).casefold()
    filtered = [
        (name, item)
        for name, item in accumulators.items()
        if not query_text or query_text in name.casefold()
    ]
    filtered.sort(
        key=lambda pair: (
            -pair[1].count,
            -pair[1].headline_count,
            -_seen_timestamp(pair[1].last_seen),
            pair[0],
        ),
    )

    total = len(filtered)
    results = [
        PersonCountResult(
            name=name,
            count=item.count,
            headline_count=item.headline_count,
            platform_keys=tuple(
                key
                for key, _count in sorted(
                    item.platform_counts.items(),
                    key=lambda pair: (-pair[1], pair[0]),
                )
            ),
            latest_title=item.latest_title,
            latest_url=item.latest_url,
            last_seen=item.last_seen,
        )
        for name, item in filtered[: max(0, int(limit))]
    ]
    return results, total
