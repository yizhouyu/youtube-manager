"""Tests for the on-screen text lint (src/editor/lint.py, retro 2026-11-08 #2): fillers and trailing
particles, one sentence split across two captions, Chinese numerals, internal references (an ERROR),
and the first mention of a glossary name without its English original.

    ./venv/bin/python scripts/test_lint_captions.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.editor import lint as L  # noqa: E402


def shot(i, subs=(), d=30, **kw):
    return dict({"id": i, "clip": "GX01", "in": 0, "out": d, "subs": list(subs)}, **kw)


def cue(t0, t1, text, **kw):
    return dict({"t0": t0, "t1": t1, "text": text}, **kw)


def run(shots, glossary=None):
    return L.onscreen_text({"project": "/nonexistent", "shots": shots}, glossary=glossary or {})


def hits(shots, needle, glossary=None):
    errors, warns = run(shots, glossary)
    return [m for m in errors + warns if needle in m]


class Fillers(unittest.TestCase):
    def test_trailing_particle(self):
        for t in ("好好看啊", "这边能看到海啊", "好多的 Kitty 啊！", "狗子累了呀", "这样就行了嘛", "真的哦", "到了啦", "走了哈"):
            self.assertIsNotNone(L.filler_warn(t), t)
        self.assertTrue(hits([shot("s1", [cue(1, 3, "小可怜啊")])], "particle"))
        self.assertTrue(hits([shot("s1", [cue(1, 3, "古时这里是避难所啊", kind="note")])], "particle"))

    def test_interjections(self):
        for t in ("我的妈呀，好高", "我的天，这么大", "哇塞，好漂亮", "哎呀，怎么搞的"):
            self.assertIn("interjection", L.filler_warn(t), t)
        self.assertIn("only an interjection", L.filler_warn("哇！"))   # captions_clean's list

    def test_left_alone(self):
        for t in ("这家菠萝店真的非常大", "我们去酒吧", "你在干嘛", "那要怎么样可以移动呢", "我们去哪里呢？",
                  "这是什么吧？", "蒜蓉的", "阿罗哈"):
            self.assertIsNone(L.filler_warn(t), t)
        # tags and titles are never treated as speech
        self.assertFalse(hits([shot("s1", tag="北岸酒吧")], "particle"))


class SplitSentence(unittest.TestCase):
    def test_dangling_end(self):
        s = [shot("s1", [cue(2.0, 4.1, "那接下来可以看一下他们很"), cue(5.0, 7.6, "重要的一个部分")])]
        self.assertTrue(hits(s, "one sentence"))

    def test_continuation_start(self):
        s = [shot("s1", [cue(0.0, 3.0, "就是 Brigham Young University"), cue(3.1, 5.0, "的夏威夷学校")])]
        self.assertTrue(hits(s, "one sentence"))
        s = [shot("s1", [cue(0.0, 2.0, "因为他们这边就是盛产"), cue(2.3, 4.0, "而且很适合生长")])]
        self.assertTrue(hits(s, "one sentence"))

    def test_unclosed_paren(self):
        s = [shot("s1", [cue(0.0, 2.0, "这个小岛（莫科利伊"), cue(2.1, 4.0, "岛）很有名")])]
        self.assertTrue(hits(s, "one sentence"))

    def test_not_split(self):
        ok = [
            ("我们今天吃这家餐车", "排了很长的队"),          # two clauses, no signal
            ("开始的这段看起来非常的平和", "后面就陡了"),      # 平和 is a word, not a dangling 和
            ("这里能看到海吗？", "在那儿"),                  # end punctuation
            ("热死了", "我知道"),
        ]
        for a, b in ok:
            self.assertFalse(hits([shot("s1", [cue(0, 2, a), cue(2.1, 4, b)])], "one sentence"), (a, b))
        far = [shot("s1", [cue(0, 2, "我觉得很"), cue(5.0, 7, "好吃")])]              # 3 s apart: a new thought
        self.assertFalse(hits(far, "one sentence"))
        long_ = [shot("s1", [cue(0, 4, "字" * 20 + "因为"), cue(4.1, 8, "字" * 10)])]  # merged cue too long
        self.assertFalse(hits(long_, "one sentence"))
        other_shot = [shot("s1", [cue(0, 2, "他们很")], d=2), shot("s2", [cue(0, 2, "重要的")])]
        self.assertFalse(hits(other_shot, "one sentence"))
        note = [shot("s1", [cue(0, 2, "我觉得很"), cue(2.1, 4, "的确如此", kind="note")])]
        self.assertFalse(hits(note, "one sentence"))

    def test_skip_collapses_the_gap(self):
        # 3 s apart in the source, but a skip removes the pause: 0.2 s on screen
        s = [shot("s1", [cue(0, 2, "我觉得很"), cue(5.0, 7, "好吃")], skip=[[2.1, 4.9]])]
        self.assertTrue(hits(s, "one sentence"))


class Digits(unittest.TestCase):
    def test_converts(self):
        self.assertEqual(L.digits_fix("她十五岁就来了"), "她15岁就来了")
        self.assertEqual(L.digits_fix("一八四四年建的"), "1844年建的")
        self.assertTrue(hits([shot("s1", [cue(0, 3, "排了二十分钟")])], "Arabic digits"))
        self.assertTrue(hits([shot("s1", tag="三个岛屿")], "Arabic digits"))    # tags and titles too

    def test_allow_list(self):
        for t in ("第一天", "一路向北", "百年老店", "我们一起去", "看一下", "有一点咸", "一些小玩具", "一样好吃",
                  "一直走", "一天下来", "四周是山", "十分好看", "一个人"):
            self.assertEqual(L.digits_fix(t), t, t)
        self.assertEqual(L.digits_fix("等了十分钟"), "等了10分钟")


class InternalRefs(unittest.TestCase):
    def test_errors(self):
        for t in ("第117期见", "下期 118 E2", "EP 121 回顾", "这是第一版", "封面 v2", "preview 版本", "预览", "117 118 119"):
            errors, _w = run([shot("s1", [cue(0, 3, t, kind="note")])])
            self.assertTrue(errors, t)
        errors, _w = run([shot("s1", title={"text": "北岸", "sub": "第122期"})])
        self.assertTrue(errors and "internal" in errors[0])
        errors, _w = run([{"id": "c1", "clip": "", "in": 0, "out": 2, "card": {"text": "draft"}}])
        self.assertTrue(errors)

    def test_not_internal(self):
        for t in ("舰上1177名官兵遇难", "1941年12月7日", "门票$198", "约120米高", "120到150米", "这条路有150年了",
                  "V8 发动机", "第一次来", "版本更新了"):
            errors, _w = run([shot("s1", [cue(0, 3, t, kind="note")])])
            self.assertFalse(errors, t)
        # a card's image file name is not on-screen text
        errors, _w = run([{"id": "c1", "clip": "", "in": 0, "out": 2, "card": {"text": "", "image": "cards/rainbow_v2.mp4"}}])
        self.assertFalse(errors)

    def test_check_blocks_render(self):
        errors, _w = L.check({"project": "/nonexistent", "shots": [shot("s1", [cue(0, 3, "第一版", kind="note")])]})
        self.assertTrue(any("internal" in e for e in errors))


class OriginalNames(unittest.TestCase):
    G = {"都乐菠萝园": ["Dole Plantation", "Dole"], "哈雷瓦": ["Haleʻiwa"], "钻石头山": ["Diamond Head"],
         "钻石山": ["Diamond Head"]}

    def test_first_mention_needs_english(self):
        s = [shot("s1", [cue(1, 3, "我们去了哈雷瓦小镇")]), shot("s2", [cue(1, 4, "Haleʻiwa 哈雷瓦很热闹", kind="note")])]
        w = hits(s, "no original name", self.G)
        self.assertEqual(len(w), 1)
        self.assertIn("Haleʻiwa", w[0])

    def test_english_nearby_or_folded(self):
        tagged = [shot("s1", [cue(1.0, 3, "就是这个都乐菠萝园")], tag="Dole 都乐菠萝园 · 上午 11:00")]
        self.assertFalse(hits(tagged, "no original name", self.G))
        folded = [shot("s1", [cue(1, 3, "哈雷瓦 Haleiwa 到了", kind="note")])]       # no ʻokina is fine
        self.assertFalse(hits(folded, "no original name", self.G))
        later_tag = [shot("s1", title={"text": "钻石头山"}, tag="Diamond Head 钻石头山", tag_at=4.0)]
        self.assertFalse(hits(later_tag, "no original name", self.G))

    def test_only_first_mention_and_aliases(self):
        s = [shot("s1", [cue(1, 3, "Diamond Head 钻石头山", kind="note"), cue(10, 12, "钻石山上好热"),
                         cue(20, 22, "钻石头山的隧道")])]
        self.assertFalse(hits(s, "no original name", self.G))

    def test_repo_glossary_loads(self):
        g = L.load_glossary()
        self.assertIn("哈雷瓦", g)
        self.assertTrue(all(isinstance(v, list) and v for v in g.values()))
        self.assertNotIn("斐济", g)                                                 # common names stay out


if __name__ == "__main__":
    unittest.main(verbosity=2)
