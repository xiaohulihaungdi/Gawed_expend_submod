"""覆盖任务分支与实际旧存档暴露的胜负队列卡死；不启动或修改游戏存档。"""
from __future__ import annotations

from validate_welyam_units_and_reforms import Model


class WarModel(Model):
    def __init__(self, effects, triggers, *, controller="A13", score=0, civil_war=True):
        super().__init__(effects, triggers)
        self.actor = "A13"
        self.controller = controller
        self.score = score
        self.civil_war = civil_war
        self.attackers = {"A50", "B83", "B84", "A52", "A51", "A24"}
        self.flags = {"gcd_welyam_civil_war_active": 0}
        self.day = 200

    def condition(self, node):
        k, v = node.key, node.value
        if k == "tag":
            return self.actor == v
        if k in {"221", "controller"}:
            old = self.actor
            if k == "controller":
                self.actor = self.controller
            result = all(self.condition(c) for c in node.children())
            self.actor = old
            return result
        if k == "is_in_war":
            return (self.civil_war and self.actor in self.attackers | {"A13"}
                    and node.scalar("casus_belli") == "cb_gcd_gawedi_civil_war"
                    and node.scalar("attacker_leader") == "A50"
                    and node.scalar("defender_leader") == "A13")
        if k == "war_with":
            # X99 模拟另打一场战争的敌人；它不能通过专用 CB 的同一战争检查。
            return v == "A13" and self.actor in self.attackers | {"REB", "X99"}
        if k == "war_score_against":
            return self.actor == "A13" and node.scalar("who") == "A50" and self.score >= float(node.scalar("value"))
        if k == "had_country_flag":
            flag = node.scalar("flag")
            return flag in self.flags and self.day - self.flags[flag] >= int(node.scalar("days"))
        return super().condition(node)


def validate(effects, triggers, missions, events, pulse):
    task = missions["a13_5_3"]
    # 第二路线边界严格为 <40；第一路线仍 >=50，40～49 不能误通过。
    for influence, privileges, allowed, event_id in (
        (29.999, 1, True, "gcd_welyam.21"),
        (30, 1, True, "gcd_welyam.21"), (39.999, 1, True, "gcd_welyam.21"), (40, 1, False, None), (49.999, 1, False, None),
        (50, 1, True, "gcd_welyam.20"),
        (20, 2, False, None),
    ):
        model = Model(effects, triggers)
        model.noble_influence, model.noble_privileges = influence, privileges
        assert model.condition(task.children("trigger")[0]) == allowed
        if allowed:
            model.execute(task.children("effect")[0])
            assert model.events == [event_id]
    # 任务悬停始终展示两种结果，不因当前符合的路线而只显示其中一个。
    assert task.children("effect")[0].children("custom_tooltip")[0].value == "gcd_welyam_task3_routes_preview_tt"

    first = Model(effects, triggers)
    first.execute(events["gcd_welyam.20"].children("option")[0])
    assert "gcd_welyam_noble_settlement" in first.ruler_modifiers
    assert "gcd_welyam_civil_war_blocked" in first.flags
    second = Model(effects, triggers)
    second.execute(events["gcd_welyam.21"].children("option")[0])
    assert second.noble_land == 15 and second.crown_land == 40
    assert second.noble_loyalty == 40
    assert second.country_modifiers == {"gcd_welyam_crown_consolidation": 3650}
    assert "gcd_welyam_civil_war_blocked" not in second.flags

    check = effects["gcd_welyam_check_civil_war_outcome_effect"]
    # 真正落入敌对内战成员手中才判陷落，叛军和无关敌国不算。
    for controller in {"A50", "B83", "B84", "A52", "A51", "A24", "REB", "X99", "A13"}:
        model = WarModel(effects, triggers, controller=controller)
        model.execute(check)
        assert model.events == (["gcd_welyam.101"] if controller in model.attackers else [])
    for score, expected in ((98.999, []), (99, ["gcd_welyam.102"]), (100, ["gcd_welyam.102"])):
        model = WarModel(effects, triggers, score=score)
        model.execute(check)
        assert model.events == expected
    unrelated = WarModel(effects, triggers, controller="A50", score=100, civil_war=False)
    unrelated.execute(check)
    assert not unrelated.events

    # 复现用户存档：旧 queued 已过数月，未记录胜者/送达，必须能重新投递。
    stuck = WarModel(effects, triggers, score=99)
    stuck.flags["gcd_welyam_civil_war_result_queued"] = 0
    stuck.execute(check)
    assert stuck.events == ["gcd_welyam.102"]
    assert stuck.flags["gcd_welyam_civil_war_crown_selected"] == 200
    stuck.execute(check)
    assert len(stuck.events) == 1
    stuck.day = 202
    stuck.execute(check)
    assert len(stuck.events) == 1
    stuck.day = 203
    stuck.execute(check)
    assert stuck.events == ["gcd_welyam.102", "gcd_welyam.102"]
    # 只有事件真正进入时才锁 delivered；此后不得重试/重复触发。
    stuck.execute(events["gcd_welyam.102"].children("immediate")[0])
    stuck.day = 300
    stuck.execute(check)
    assert len(stuck.events) == 2
    assert not stuck.condition(events["gcd_welyam.102"].children("trigger")[0])

    # 首都陷落优先于同时达到 99 分；选定后不会因省份夺回而改成另一个结局。
    locked = WarModel(effects, triggers, controller="A50", score=100)
    locked.execute(check)
    locked.controller, locked.day = "A13", 203
    locked.execute(check)
    assert locked.events == ["gcd_welyam.101", "gcd_welyam.101"]
    crown_locked = WarModel(effects, triggers, score=99)
    crown_locked.execute(check)
    crown_locked.controller, crown_locked.day = "A50", 203
    crown_locked.execute(check)
    assert crown_locked.events == ["gcd_welyam.102", "gcd_welyam.102"]
    assert not crown_locked.condition(events["gcd_welyam.101"].children("trigger")[0])
    # 自动国家事件路径必须能在没有成功脚本投递时，独立满足触发条件。
    auto_crown = WarModel(effects, triggers, score=99)
    auto_crown.flags["gcd_welyam_civil_war_result_queued"] = 0
    assert auto_crown.condition(events["gcd_welyam.102"].children("trigger")[0])
    auto_lords = WarModel(effects, triggers, controller="B83")
    assert auto_lords.condition(events["gcd_welyam.101"].children("trigger")[0])
    assert not auto_lords.condition(events["gcd_welyam.102"].children("trigger")[0])
    for eid in ("gcd_welyam.101", "gcd_welyam.102"):
        assert not events[eid].children("is_triggered_only")
        assert events[eid].scalar("fire_only_once") == "yes"
        assert events[eid].children("mean_time_to_happen")[0].scalar("days") == "1"
    # 日检翻转明确进入 A13；不再出现不明确作用域的 province_flag 条件。
    assert pulse.children("trigger")[0].children("A13")
    assert not any(n.key == "has_province_flag" for n in pulse.walk())
    assert not any(n.key == "can_spawn_rebels" for n in triggers["gcd_welyam_safe_rebel_province_trigger"].walk())
