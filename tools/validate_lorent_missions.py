"""检查洛伦特附庸计数、送礼边界、奖励对象与贝维克修正；不启动游戏。"""
from __future__ import annotations

from copy import deepcopy
import re

from pdx_script import parse


class MissionCheck:
    def __init__(self, countries, triggers):
        self.countries, self.triggers = countries, triggers
        self.claims, self.modifiers = [], []

    def condition(self, node, actor="A13", params=None):
        params = params or {}
        k, v = node.key, node.value
        children = [n for n in node.children() if n.key != "tooltip"]
        country = self.countries[actor]
        if k in {"trigger", "AND", "custom_trigger_tooltip"}:
            return all(self.condition(n, actor, params) for n in children)
        if k == "OR":
            return any(self.condition(n, actor, params) for n in children)
        if k == "NOT":
            return not all(self.condition(n, actor, params) for n in children)
        if k == "calc_true_if":
            candidates = node.children("all_country")[0].children()
            return sum(all(self.condition(n, tag, params) for n in candidates)
                       for tag in self.countries) >= int(node.scalar("amount"))
        if k in self.countries:
            return all(self.condition(n, k, params) for n in children)
        if k in self.triggers:
            arguments = {n.key: n.value for n in children} if children else params
            return all(self.condition(n, actor, arguments)
                       for n in self.triggers[k].children())
        if k == "exists":
            return country.get("exists", True) == (v == "yes")
        if k == "tag":
            return actor == v
        if k == "is_subject_of":
            return country.get("overlord") == v
        if k == "is_vassal":
            return country.get("vassal", False) == (v == "yes")
        if k in {"has_opinion", "has_opinion_modifier", "has_spy_network_from"}:
            who = node.scalar("who")
            if who.startswith("$"):
                who = params[who.strip("$")]
            who = "A13" if who == "ROOT" else who
            field = {"has_opinion": "opinion", "has_opinion_modifier": "gift",
                     "has_spy_network_from": "spy"}[k]
            if k == "has_opinion_modifier":
                assert node.scalar("modifier") == "sent_gift"
            return country.get(field, {}).get(who, 0) >= float(node.scalar("value"))
        raise AssertionError(("未支持的任务条件", k))

    def execute(self, node, actor="A13"):
        for entry in node.children():
            k = entry.key
            if k in self.countries:
                self.execute(entry, k)
            elif k == "hidden_effect":
                self.execute(entry, actor)
            elif k == "every_subject_country":
                for tag, country in self.countries.items():
                    if country.get("overlord") == actor and all(
                        self.condition(n, tag) for n in entry.children("limit")[0].children()
                    ):
                        self.execute(entry, tag)
            elif k == "add_liberty_desire":
                country = self.countries[actor]
                country["liberty"] = min(100, country.get("liberty", 0) + float(entry.value))
            elif k == "small_country_region":
                self.claims.append((entry.children()[0].key, entry.children()[0].value))
            elif k == "add_country_modifier":
                self.modifiers.append((actor, entry.scalar("name"), int(entry.scalar("duration"))))
            elif k not in {"limit", "custom_tooltip"}:
                raise AssertionError(("未支持的任务效果", k))


def validate(missions, helper_tree, modifiers, anb):
    # 读取实际 Anbennar 送礼条件，防止把 +25 关系误解为 25 杜卡特。
    native = parse((anb / "common/scripted_triggers/anb_scripted_triggers.txt")
                   .read_text(encoding="utf-8-sig"))
    gift = native.children("has_25_opinion_sent_gift")[0]
    triggers = {n.key: n for n in helper_tree.children()}
    triggers[gift.key] = gift
    world = {"A13": {}, "A01": {"spy": {"A13": 30}}}
    for tag in ("A09", "A08", "B68", "A03", "A64", "A02"):
        world[tag] = {"overlord": "A01", "vassal": True,
                      "opinion": {"A13": 125}, "gift": {"A13": 25}, "liberty": 10}
    world["B68"]["gift"]["A13"] = 24.999
    world["A64"]["vassal"] = False  # 其他类型的属国不能冒充附庸。
    world["A02"]["overlord"] = "A13"  # 非洛伦特附庸不能计入。
    trigger = missions["a13_1_1"].children("trigger")[0]
    assert MissionCheck(deepcopy(world), triggers).condition(trigger)
    for tag, field, value in (
        ("A01", "spy", 29.999), ("A08", "opinion", 124.999),
        ("A08", "gift", 24.999),
    ):
        check = MissionCheck(deepcopy(world), triggers)
        check.countries[tag][field]["A13"] = value
        assert not check.condition(trigger), (tag, field, value)
    # 一国关系合格、另一国送礼合格不能拼成两个合格国家。
    split = MissionCheck(deepcopy(world), triggers)
    split.countries["A09"]["gift"]["A13"] = 0
    split.countries["A08"]["opinion"]["A13"] = 124
    assert not split.condition(trigger)
    # 检查的是我国在洛伦特的网络；反方向或第三国的网络不能代替。
    reversed_network = MissionCheck(deepcopy(world), triggers)
    reversed_network.countries["A01"]["spy"] = {"A02": 100}
    reversed_network.countries["A13"]["spy"] = {"A01": 100}
    assert not reversed_network.condition(trigger)

    check = MissionCheck(deepcopy(world), triggers)
    check.countries["B68"]["gift"]["A13"] = 25
    check.countries["B68"]["liberty"] = 80
    check.execute(missions["a13_1_1"].children("effect")[0])
    assert {tag for tag in world if check.countries[tag].get("liberty") != world[tag].get("liberty")} == {"A09", "A08", "B68"}
    assert check.countries["A09"]["liberty"] == check.countries["A08"]["liberty"] == 60
    assert check.countries["B68"]["liberty"] == 100
    assert check.claims == [("add_claim", "ROOT")]
    assert check.modifiers == [("A01", "bumandebanshenren", 7300)]
    assert modifiers.children("bumandebanshenren")[0].scalar("defensiveness") == "-0.2"
    assert parse((anb / "map/region.txt").read_text(encoding="utf-8-sig")).children("small_country_region")

    # 图三来自原版任务，逐项核对三种修正；期限单独保持 20 年。
    # 只读取本次涉及的定义，避开大型原版文件中与本任务无关的语法扩展。
    native_text = (anb / "common/event_modifiers/anb_mission_modifiers.txt").read_text(encoding="utf-8-sig")
    native_block = re.search(r"(?m)^adshaw_battle_for_bayvic\s*=\s*\{[^{}]*\}", native_text)
    assert native_block
    native_mods = parse(native_block[0])
    values = lambda node: {n.key: n.value for n in node.children()}
    assert values(modifiers.children("tongzhibeiweik")[0]) == values(native_mods.children("adshaw_battle_for_bayvic")[0])
    reward = missions["a13_4_2"].children("effect")[0].children("add_country_modifier")[0]
    assert reward.scalar("name") == "tongzhibeiweik" and reward.scalar("duration") == "7300"
