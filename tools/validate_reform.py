"""校验改革脚本结构、引用和关键分支；不启动 EU4，不替代游戏引擎验证。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

from check_encoding import errors
from event_notes import strip_notes
from check_event_structure import errors as event_errors
from pdx_script import Node, parse
from validate_welyam_units_and_reforms import validate as validate_units_and_reforms
from validate_welyam_routes_and_outcomes import validate as validate_routes_and_outcomes
from validate_lorent_missions import validate as validate_lorent_missions

ROOT = Path(__file__).resolve().parent.parent


def normalized(node):
    return (node.key, node.op, [normalized(n) for n in node.children()]
            if isinstance(node.value, list) else node.value)


def decode_special(text):
    def byte(char):
        return ord(char) if ord(char) < 256 else char.encode("cp1252")[0]
    result, pos = [], 0
    while pos < len(text):
        marker = ord(text[pos])
        if 0x10 <= marker <= 0x13:
            low, high = byte(text[pos + 1]), byte(text[pos + 2])
            if marker & 1:
                low -= 14
            if marker & 2:
                high += 9
            result.append(chr(high << 8 | low))
            pos += 3
        else:
            result.append(text[pos])
            pos += 1
    return "".join(result)


class TimerCheck:
    """只解释计时所用的简单条件/标记，直接运行实际 AST，检查边界与停用行为。"""
    def __init__(self, effects, disaster=True, loyalty=19, free_rebel_province=True):
        self.effects = effects
        self.flags = {}
        self.day = 0
        self.disaster = disaster
        self.loyalty = loyalty
        self.events = []
        self.removed = []
        self.rebel_attempts = 0
        self.daily_calls = 0
        self.free_rebel_province = free_rebel_province

    def condition(self, node):
        k, v = node.key, node.value
        if k in {"ROOT", "limit", "AND"}:
            return all(self.condition(n) for n in node.children())
        if k == "OR":
            return any(self.condition(n) for n in node.children())
        if k == "NOT":
            return not all(self.condition(n) for n in node.children())
        if k == "has_disaster":
            return self.disaster
        if k == "has_country_flag":
            return v in self.flags
        if k == "had_country_flag":
            f = node.scalar("flag")
            return f in self.flags and self.day - self.flags[f] >= int(node.scalar("days"))
        if k == "estate_loyalty":
            return self.loyalty >= float(node.scalar("loyalty"))
        if k == "tag":
            return v == "A13"
        if k == "any_owned_province":
            # 具体省份资格由单位模型检查，这里只模拟是否存在可用省份。
            return self.free_rebel_province
        # 战争结果由下方的结构检查覆盖，不模拟引擎的 is_in_war。
        raise AssertionError(f"计时检查遇到未支持条件：{k}")

    def execute(self, node):
        branch = None
        for n in node.children():
            k, v = n.key, n.value
            if k == "if":
                branch = self.condition(n.children("limit")[0])
                if branch:
                    self.execute(n)
            elif k == "else_if":
                if not branch and self.condition(n.children("limit")[0]):
                    self.execute(n)
                    branch = True
            elif k == "else":
                if not branch:
                    self.execute(n)
                branch = None
            elif k in {"limit", "custom_tooltip"}:
                continue
            elif k == "set_country_flag":
                self.flags[v] = self.day
            elif k == "clr_country_flag":
                self.flags.pop(v, None)
            elif k == "remove_country_modifier":
                self.removed.append(v)
            elif k == "country_event":
                self.events.append(n.scalar("id"))
            elif k == "gcd_welyam_check_civil_war_outcome_effect":
                continue
            elif k == "gcd_welyam_try_spawn_fixed_rebels_effect":
                # 单位处理由独立的团数检查覆盖；此模型没有空省，只记录是否发起尝试。
                self.rebel_attempts += 1
            elif k in self.effects:
                if k == "gcd_welyam_daily_reform_effect":
                    self.daily_calls += 1
                self.execute(self.effects[k])
            else:
                raise AssertionError(f"计时检查遇到未支持效果：{k}")


def validate(anb: Path, game: Path):
    assert not errors(ROOT), errors(ROOT)
    trees = {}
    for folder in ("common", "events", "missions"):
        for file in (ROOT / folder).rglob("*.txt"):
            if file.name == "gcd_city_development.txt":
                continue  # 与本次内容无关的 GUI DSL 不纳入此读取器。
            trees[file.relative_to(ROOT).as_posix()] = parse(file.read_text(encoding="utf-8-sig"))
    effect_nodes = [n for path, tree in trees.items() if path.startswith("common/scripted_effects/") for n in tree.children()]
    effect_tree = Node("ROOT", effect_nodes, 0, 0)
    effects = {n.key: n for n in effect_nodes}
    triggers = {n.key: n for n in trees["common/scripted_triggers/gcd_welyam_reform_triggers.txt"].children()}
    events = {n.scalar("id"): n for n in trees["events/gcd_welyam_reform_events.txt"].children("country_event")}
    assert len(events) == 13
    # 修正（闪退）：检查隐藏事件的必要选项及 immediate 中经过 scripted effect 的事件调用环。
    assert not event_errors(trees["events/gcd_welyam_reform_events.txt"],
                            effect_tree)
    # 回归：确实能拒绝本次发生栈溢出的历史版本，而非仅证明修复版能被括号读取器接受。
    bad_events = parse(subprocess.check_output([
        "git", "show", "3b62e30:events/gcd_welyam_reform_events.txt"], cwd=ROOT).decode("utf-8"))
    bad_effects = parse(subprocess.check_output([
        "git", "show", "3b62e30:common/scripted_effects/gcd_welyam_reform_effects.txt"], cwd=ROOT).decode("utf-8"))
    rejected = event_errors(bad_events, bad_effects)
    assert any("gcd_welyam.90 缺少" in p for p in rejected)
    assert any("gcd_welyam.2 缺少" in p for p in rejected)
    assert any("immediate 事件调用环" in p and "gcd_welyam.90" in p for p in rejected)
    # 回归：上一次把循环移到 option 的版本仍有 .90 -> .90，必须被新检查拒绝。
    previous_events = parse(subprocess.check_output([
        "git", "show", "3f3eb13:events/gcd_welyam_reform_events.txt"], cwd=ROOT).decode("utf-8"))
    previous_effects = parse(subprocess.check_output([
        "git", "show", "3f3eb13:common/scripted_effects/gcd_welyam_reform_effects.txt"], cwd=ROOT).decode("utf-8"))
    assert any("含选项和延迟的 事件调用环" in p and "gcd_welyam.90" in p
               for p in event_errors(previous_events, previous_effects))
    # .90 只保留旧存档兼容入口，不能再由代码安排下一次。
    for effect in effects.values():
        assert not any(n.key == "country_event" and n.scalar("id") == "gcd_welyam.90" for n in effect.walk())
    for event in events.values():
        for block in event.children("option") + event.children("immediate") + event.children("after"):
            assert not any(n.key == "country_event" and n.scalar("id") == "gcd_welyam.90" for n in block.walk())
    mods = {n.key: n for n in trees["common/event_modifiers/gcd_welyam_reform_modifiers.txt"].children()}
    assert len(mods) == 6

    # 所有新增事件、修正、脚本效果/条件、本地化键均应有定义。
    source = (ROOT / "制作源文件/威利亚姆改革_中文原文.yml").read_text(encoding="utf-8-sig")
    local = (ROOT / "localisation/gcd_welyam_reform_l_english.yml").read_text(encoding="utf-8-sig")
    assert decode_special(local) == source
    keys = re.findall(r"^\s*([\w.]+):\d+ ", source, re.M)
    assert len(keys) == len(set(keys))
    for path, tree in trees.items():
        for n in tree.walk():
            if n.key == "country_event" and isinstance(n.value, list):
                event_id = n.scalar("id", "")
                if event_id.startswith("gcd_welyam."):
                    assert event_id in events, (path, event_id)
            if n.key in {"title", "desc", "name", "custom_tooltip", "tooltip"} and isinstance(n.value, str):
                if n.value.startswith("gcd_welyam"):
                    assert n.value in keys or n.value in mods, (path, n.value)
            if n.key.startswith("gcd_welyam_") and n.key.endswith("_effect"):
                assert n.key in effects, (path, n.key)
            if n.key.startswith("gcd_welyam_") and n.key.endswith("_trigger"):
                assert n.key in triggers, (path, n.key)

    # 图标、国家、战事目标均来自本机依赖，避免把显示名当国家代码。
    gfx = "\n".join(f.read_text(encoding="utf-8-sig", errors="replace")
                    for root in (game, anb) for f in (root / "interface").rglob("*.gfx"))
    for e in events.values():
        if e.scalar("picture"):
            assert re.search(r'\bname\s*=\s*"?' + re.escape(e.scalar("picture")) + r'\b', gfx)
    tags = (anb / "common/country_tags/anb_countries.txt").read_text(encoding="utf-8-sig")
    for tag in ("A13", "A50", "B83", "B84", "A52", "A51", "A24"):
        assert re.search(r"^" + tag + r"\s*=", tags, re.M)
    assert 'capital = 221' in (anb / "history/countries/A13 - Gawed.txt").read_text(encoding="utf-8-sig")
    assert (game / "gfx/interface/disasters/civil_war.dds").exists()

    # 保留未授权改动的前四列、原稿、原版禁用文件；任务依赖仍无环。
    missions = trees["missions/a13_stage1_missions.txt"]
    original = parse(subprocess.check_output(["git", "show", "acd61b7:missions/a13_stage1_missions.txt"], cwd=ROOT).decode("utf-8"))
    # 同步前发现安装目录已有两处图标互换；只允许并保留这两处，其余前四列须与基线相同。
    local_icons = {"a13_1_1": "mission_sunyanin", "a13_2_1": "contracts_of_correspondence"}
    for col in original.children():
        for mission in col.children():
            if mission.key in local_icons:
                mission.children("icon")[0].value = local_icons[mission.key]
            if mission.key in {"a13_1_1", "a13_2_1", "a13_3_1", "a13_3_2"}:
                # 本轮任务一调整，并合并本机已有的任务二、任务三改动，防止同步覆盖。
                current = next(n for column in missions.children() for n in column.children()
                               if n.key == mission.key)
                for key in ("trigger", "effect"):
                    mission.children(key)[0].value = current.children(key)[0].value
    assert [normalized(n) for n in missions.children()[:4]] == [normalized(n) for n in original.children()[:4]]
    assert (ROOT / "missions/Gawedi_Missions.txt").read_bytes() == subprocess.check_output(
        ["git", "show", "acd61b7:missions/Gawedi_Missions.txt"], cwd=ROOT)
    all_missions = {n.key: n for col in missions.children() for n in col.children() if re.fullmatch(r"a13_\d_\d", n.key)}
    assert len(all_missions) == 20
    validate_lorent_missions(all_missions, trees["common/scripted_triggers/gcd_a13_mission_triggers.txt"],
                             trees["common/event_modifiers/a13_mission_modifiers1.txt"], anb)
    def visit(mid, stack):
        assert mid not in stack, ("循环依赖", mid)
        for dep in all_missions[mid].children("required_missions"):
            for entry in dep.children():
                assert entry.key in all_missions
                visit(entry.key, stack | {mid})
    for mid in all_missions:
        visit(mid, set())

    # 持续低于 20 满 365 天才触发，正好 20 重置，豁免与灾难结束后均不能触发。
    clock = TimerCheck(effects)
    daily = effects["gcd_welyam_daily_reform_effect"]
    for day in range(365):
        clock.day = day
        clock.execute(daily)
    assert "gcd_welyam.100" not in clock.events
    clock.day = 365
    clock.execute(daily)
    assert clock.events.count("gcd_welyam.100") == 1
    clock.day = 366
    clock.execute(daily)
    assert clock.events.count("gcd_welyam.100") == 1
    reset = TimerCheck(effects)
    reset.execute(daily)
    reset.day, reset.loyalty = 364, 20
    reset.execute(daily)
    assert "gcd_welyam_low_nobles_since" not in reset.flags
    reset.day, reset.loyalty = 365, 19
    reset.execute(daily)
    reset.day = 729
    reset.execute(daily)
    assert not reset.events
    reset.day = 730
    reset.execute(daily)
    assert reset.events == ["gcd_welyam.100"]
    for state in ("blocked", "ended"):
        c = TimerCheck(effects, disaster=state != "ended")
        c.flags["gcd_welyam_low_nobles_since"] = 0
        if state == "blocked":
            c.flags["gcd_welyam_civil_war_blocked"] = 0
        c.day = 1000
        c.execute(daily)
        assert not c.events
    # 两年接口不会在完成任务二或灾难结束后继续触发，也没有偷换成缩放叛军。
    for ended, stopped in ((False, False), (False, True), (True, False)):
        c = TimerCheck(effects, disaster=not ended, loyalty=50)
        c.day = 730
        c.flags["gcd_welyam_rebel_clock"] = 0
        if stopped:
            c.flags["gcd_welyam_rebel_spawn_stopped"] = 0
        c.execute(daily)
        assert ("gcd_welyam_fixed_rebels_due" in c.flags) == (not ended and not stopped)
        assert c.events.count("gcd_welyam.91") == int(not ended and not stopped)
    # 不重复投递；没有空省先保留到期状态，有空省再投递一次隐藏事件。
    waiting = TimerCheck(effects, loyalty=50, free_rebel_province=False)
    waiting.flags["gcd_welyam_rebel_clock"] = 0
    waiting.day = 730
    waiting.execute(daily)
    assert not waiting.events and "gcd_welyam_fixed_rebels_due" in waiting.flags
    waiting.free_rebel_province, waiting.day = True, 731
    waiting.execute(daily)
    waiting.day = 732
    waiting.execute(daily)
    assert waiting.events == ["gcd_welyam.91"]
    # 原生回调与旧存档兼容入口同一天同时运行，也只能执行一次。
    once = TimerCheck(effects, loyalty=50)
    once.flags["gcd_welyam_daily_pulse_installed"] = 0
    once.execute(effects["gcd_welyam_run_daily_once_effect"])
    once.execute(effects["gcd_welyam_run_daily_once_effect"])
    assert once.daily_calls == 1
    once.day = 1
    once.execute(effects["gcd_welyam_run_daily_once_effect"])
    assert once.daily_calls == 2
    once.disaster = False
    once.day = 2
    once.execute(effects["gcd_welyam_run_daily_once_effect"])
    assert once.daily_calls == 2

    # 解禁只移除本灾难施加的标记；其他来源的禁令保留。
    for owned in (True, False):
        c = TimerCheck(effects)
        c.flags["estate_burghers_indebted_to_burghers_disabled"] = 0
        if owned:
            c.flags["gcd_welyam_owns_burgher_loan_lock"] = 0
        c.execute(effects["gcd_welyam_unlock_burgher_loans_effect"])
        assert ("estate_burghers_indebted_to_burghers_disabled" in c.flags) == (not owned)
    m2 = all_missions["a13_5_2"].children("effect")[0]
    assert any(n.key == "gcd_welyam_unlock_burgher_loans_effect" for n in m2.walk())
    assert "解除威利亚姆改革施加的富商贷款禁令" in source
    validate_units_and_reforms(effects, triggers, all_missions, events, anb)
    validate_routes_and_outcomes(effects, triggers, all_missions, events,
        trees["common/province_triggered_modifiers/gcd_welyam_daily_pulse.txt"].children("gcd_welyam_daily_pulse")[0])

    # 精确核对两种结局的名单及事件来源；首都控制者必须属于本次战争的攻击方。
    crown = effects["gcd_welyam_crown_victory_effect"]
    assert {n.value for n in crown.walk() if n.key == "inherit"} == {"A50", "B83", "B84", "A52", "A51", "A24"}
    lords = effects["gcd_welyam_lords_victory_effect"]
    assert {n.value for n in lords.walk() if n.key == "vassalize"} == {"B83", "B84", "A52", "A51"}
    assert {n.value for n in lords.walk() if n.key == "inherit"} == {"A13"}
    outcome = effects["gcd_welyam_check_civil_war_outcome_effect"]
    assert any(n.key == "gcd_welyam_capital_lost_trigger" for n in outcome.walk())
    assert any(n.key == "war_score_against" and n.scalar("value") == "99" for n in outcome.walk())
    assert {n.scalar("id") for n in outcome.walk() if n.key == "country_event"} == {"gcd_welyam.101", "gcd_welyam.102"}
    active = triggers["gcd_welyam_civil_war_active_trigger"]
    assert active.children("is_in_war")[0].scalar("casus_belli") == "cb_gcd_gawedi_civil_war"
    assert any(n.key == "release_all_possible_countries" for n in effects["gcd_welyam_start_civil_war_effect"].walk())

    # 第一分支独有豁免，第二分支十年；十五年卡丽娜分支是额外 +2、合计 +4。
    options = events["gcd_welyam.20"].children("option")
    assert any(n.key == "set_country_flag" and n.value == "gcd_welyam_civil_war_blocked" for n in options[0].walk())
    assert not any(n.key == "set_country_flag" and n.value == "gcd_welyam_civil_war_blocked" for n in options[1].walk())
    assert next(n for n in options[0].walk() if n.key == "add_ruler_modifier").scalar("duration") == "-1"
    assert next(n for n in events["gcd_welyam.21"].walk() if n.key == "add_country_modifier").scalar("duration") == "3650"
    assert next(n for n in events["gcd_welyam.10"].walk() if n.key == "add_ruler_modifier").scalar("duration") == "-1"
    assert {n.scalar("duration") for n in events["gcd_welyam.30"].walk() if n.key == "add_country_modifier"} == {"5475"}
    assert mods["gcd_welyam_great_hunt_karina"].scalar("diplomatic_reputation") == "4"
    cleanup = effects["gcd_welyam_cleanup_reform_effect"]
    assert {n.value for n in cleanup.walk() if n.key == "remove_country_modifier"} == set(mods)
    assert any(n.key == "all_subject_country" for n in all_missions["a13_5_4"].children("trigger")[0].walk())

    # 兼容文件剥去插入片段之后与 Anbennar 原文件逐字节一致。
    bases = json.loads((ROOT / "制作源文件/改革兼容基线.json").read_text(encoding="utf-8"))
    for path in bases:
        content = (ROOT / path).read_bytes()
        # 新增：移除说明注释后，仍逐字节核对原版兼容文件，避免注释掩盖逻辑改动。
        clean = strip_notes(content.decode("utf-8")).encode("utf-8")
        clean = re.sub(rb'\r?\n    # GCD_REFORM_BEGIN ([a-z_]+)\r?\n.*?    # GCD_REFORM_END \1\r?\n', b"", clean, flags=re.S)
        assert clean == (anb / path).read_bytes().removeprefix(b"\xef\xbb\xbf"), path
        assert hashlib.sha256(content).hexdigest() == bases[path]["generated_sha256"]
    print("Reform validation passed: syntax/references, 20 missions, Lorent subject/gift boundaries, Bayvic values, timer boundaries, disaster shutdown, loan unlock, outcomes, durations, compatibility and encoding.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("anb_root", type=Path)
    parser.add_argument("game_root", type=Path)
    args = parser.parse_args()
    validate(args.anb_root, args.game_root)
