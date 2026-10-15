"""Chinese numerals → Arabic digits in captions (creator, 2026-10-15: 「能用数字的地方，你就用数字」).

    ./venv/bin/python -m src.editor.digits "<project>"          # list proposed changes
    ./venv/bin/python -m src.editor.digits "<project>" --apply  # write them to edl.json (backup in edit/history)

Conservative: converts a numeral only when a counting/measure unit follows (年 岁 个 块 比索 世纪 号 月 公里 …)
or it is a year / decimal. Keeps set phrases and ordinals: 一个 (article), 一下, 一路, 第一天, 百年老店, 四成.
"""
import json
import os
import re
import shutil
import sys
import time

from . import edl as E

D = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
NUM = "零〇一二两三四五六七八九十百千"
UNITS = ("年代", "年", "岁", "个", "块钱", "块", "美元", "美金", "刀", "比索", "世纪", "号", "日", "月", "公里", "英里",
         "公斤", "斤", "磅", "米", "度", "分钟", "分", "秒", "小时", "层", "种", "样", "只", "头", "辆", "座", "间", "道",
         "家", "张", "杯", "碗", "盘", "份", "位", "人", "次", "遍", "周", "星期", "万", "%")


def cn2int(s):
    if all(c in D for c in s) and len(s) > 1:      # digit string: 一八四四 → 1844
        return int("".join(str(D[c]) for c in s))
    total, sect, cur = 0, 0, 0
    for c in s:
        if c in D:
            cur = D[c]
        elif c == "十":
            sect += (cur or 1) * 10; cur = 0
        elif c == "百":
            sect += cur * 100; cur = 0
        elif c == "千":
            sect += cur * 1000; cur = 0
    return total + sect + cur


UNIT_RX = "|".join(map(re.escape, UNITS))
# a numeral + optional 多 + unit; or a 零点… decimal (other X点Y is usually a clock time: 三点四十)
RX = re.compile(rf"(第)?([{NUM}]+)(点[{NUM}]+)?(?=(多?(?:{UNIT_RX})))|(第)?(零)(点[{NUM}]+)()")


RANGE = re.compile(rf"(?<![第{NUM}])([{NUM}]+)(到|至)(?=[{NUM}])")


def convert(text):
    def rep(m):
        if m.group(6):
            return "0." + "".join(str(D[c]) for c in m.group(7)[1:])
        ordinal, n, dec, unit = m.group(1), m.group(2), m.group(3), m.group(4).lstrip("多")
        if dec and n != "零":                        # 三点四十 = a clock time, not 3.4
            return m.group(0)
        if ordinal:
            return m.group(0)
        if n in ("一", "两") and not dec:           # 一个/一家/两个人: articles and loose counts stay Chinese
            return m.group(0)
        after = m.string[m.end():]
        if (unit == "分" and after[1:2] == "之") or (unit == "块" and after[1:2] in D):
            return m.group(0)                       # 三分之一 (fraction), 四块九五 (spoken price)
        if len(n) > 1 and all(c in D for c in n) and not (unit.startswith("年") and len(n) == 4):
            return m.group(0)                       # 三四个 = "three or four"; only 一八四四年-style years are digit strings
        if n in ("百", "千", "万"):                  # 百年老店
            return m.group(0)
        try:
            v = str(cn2int(n))
        except Exception:
            return m.group(0)
        if dec:
            v += "." + "".join(str(D[c]) for c in dec[1:])
        return v
    # 十到十五分钟: the first end of a range takes the second end's unit
    text = RANGE.sub(lambda m: (str(cn2int(m.group(1))) if m.group(1) not in ("一", "两") else m.group(1)) + m.group(2)
                     if RX.match(m.string, m.end()) else m.group(0), text)
    return RX.sub(rep, text)


def main(project, apply=False):
    path = E.edl_path(project)
    d = json.load(open(path, encoding="utf-8"))
    n = 0
    for s in d["shots"]:
        for u in s.get("subs", []):
            new = convert(u["text"])
            if new != u["text"]:
                n += 1
                print(f"{s['id']}: {u['text']}\n    → {new}")
                if apply:
                    u["text"] = new
    if apply and n:
        hist = os.path.join(E.edit_dir(project), "history")
        os.makedirs(hist, exist_ok=True)
        shutil.copy(path, os.path.join(hist, f"edl.{time.strftime('%H%M%S')}-pre-digits.json"))
        json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"{n} caption(s) {'changed' if apply else 'would change'}")


if __name__ == "__main__":
    main(sys.argv[1], "--apply" in sys.argv)
